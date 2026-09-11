# Technical Design: Image Layer & Model Run Loading Performance

## Overview

Collapse the `GetProjectDetails` request from `O(layers × models)` sequential storage
round-trips to a small constant by (1) hoisting redundant reads out of loops,
(2) batch-loading each metadata type **once per partition** and joining in memory,
(3) parallelizing genuinely independent I/O, and (4) pushing filtering into the data
layer. Add HTTP caching so unchanged data isn't recomputed. On the UI, stop the
20-second full-project poll from thrashing the render tree by adding change-detection,
context splitting, and memoization. Backend fixes are sequenced first because they are
the dominant cost and are transparent to the UI.

## Architecture

```
┌──────────────┐   GetProjectDetails    ┌────────────────────┐   1 read / type   ┌──────────────┐
│   React UI   │───────────────────────▶│   hastefuncapi      │──────────────────▶│ Blob / Cosmos │
│  Project.jsx │  (ETag / 304 aware)    │  GetProjectDetails   │  (batched+joined)  │  data layer  │
└──────────────┘                        └─────────┬──────────┘                    └──────────────┘
      ▲ smart poll (304 fast-path)                │ uses
      │                                  ┌─────────▼──────────┐
      └── memoized rows, split context   │  MetadataProcessor  │  load_filtered() /
                                         │  (+ load_map cache) │  load_all_from_partition (prefix)
                                         └────────────────────┘
```

## API Design

### `GET /api/GetProjectDetails` — reworked internals (contract unchanged by default)

Same request/response shape by default, so the UI keeps working during rollout. New
**optional** query params enable the lighter paths incrementally:

| Param | Type | Default | Effect |
|---|---|---|---|
| `includeModels` | bool | existing | unchanged |
| `includeArtifacts` | bool | `true` (compat) | when `false`, skip B2's per-model artifact/label expansion; return `modelCount` + model summaries only |
| `summary` | bool | `false` | return per-layer counts (`modelCount`, `labelProjectCount`, `validationLabelCount`) without nested `models[]` — the shape the list view actually needs |

**New response headers:** `ETag` (hash of the serialized payload) and
`Cache-Control: private, max-age=15`. On a conditional request whose `If-None-Match`
matches, return `304` with an empty body.

### Reworked handler logic (replaces [function_app.py:534-638](../../../api/hastefuncapi/function_app.py#L534-L638))

```python
# 1. Independent top-level reads in parallel
project, image_layers, models, label_projects = await asyncio.gather(
    _load(PROJECT.load, project_id),
    _load(IMAGELAYER.load_all_from_partition),
    _load(MODEL.load_all_from_partition) if include_models else _none(),
    _load(LABELS.load_all_from_partition),          # ONCE, not per-layer (fixes B1)
)

# 2. Index once, join in memory — no per-item I/O
models_by_layer   = group_by(models or [], "imageLayerId")
labels_by_layer   = index_by(label_projects, "imageLayerId")

# 3. Validation + (optional) artifacts: batch in parallel, bounded concurrency
validation_by_layer = await gather_map(
    {l["imageLayerId"]: VALIDATION.load for l in image_layers}
)   # fixes B3
if include_models and include_artifacts:
    artifacts_by_model, labelsurl_by_model = await gather_models(models)  # fixes B2

# 4. Assemble response purely in memory, then sort.
```

Key point: every metadata **type** is read at most once per partition (a handful of
`load_all_from_partition` calls), plus one bounded-parallel batch for the per-key
`VALIDATION`/artifact reads. Total round-trips become a small constant + at most two
bounded-concurrency fan-outs, independent of `L × M` sequencing.

## Internal Interfaces (hastegeo)

| Module | Change | Signature | Purpose |
|---|---|---|---|
| `core/processors/metadata.py` | **new** | `load_filtered(self, predicate: dict) -> list` | Filter in the data layer, not the caller (fixes H3, B1, Q2). Backed by prefix scan + property match. |
| `core/processors/metadata.py` | **new** | `load_map(self, keys: list[str], max_workers=8) -> dict` | Parallel multi-key load with bounded `ThreadPoolExecutor` (powers B2/B3 batches). |
| `core/data_layer/azure_blob_storage_data_layer.py` | **fix** | `load_all(..., name_starts_with=None)` | Always pass a prefix; add optional metadata-only listing (fixes H1). |
| `core/data_layer/azure_blob_storage_data_layer.py` | **fix** | parallel download loop | Bounded `ThreadPoolExecutor` in `load_all*` and artifact `fetch_artifact` (fixes H2). |
| `core/data_layer/azure_blob_storage_data_layer.py` | **fix** | remove double `json.loads` | Single-serialize on save; delete re-parse (fixes H4). |
| `core/blob.py` | **fix** | module-level `BlobServiceClient` singleton keyed by conn-string | Reuse client (fixes H5). |
| `core/artifact_storage/azure_blob_artifact_storage.py` | **fix** | parallel `fetch_artifact` | Same `ThreadPoolExecutor` pattern (fixes H2). |

`load_map` sketch:

```python
def load_map(self, keys, max_workers=8):
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(self._safe_load, k): k for k in keys}
        for fut in futs:
            out[futs[fut]] = fut.result()   # None on FileNotFoundError
    return out
```

The API layer calls `await asyncio.to_thread(processor.load_map, keys)` so one thread
hop wraps the whole bounded-parallel batch instead of one hop per key.

## Queue design (Phase 3)

- `GetCreateModelRunQueueTrigger`: replace `load_all_from_partition` + Python filter
  with `load_filtered({"imageLayerId": ...})` (Q2).
- Inference / image triggers: wrap independent loads in `asyncio.gather` (Q3).
- Add `MetadataProcessor.save_batch(items)` and collect intermediate writes (Q4).
- `host.json`: evaluate `batchSize` > 1 for I/O-bound triggers and
  `maxDequeueCount` ≥ 3 with a real poison path (Q1); raise `visibilityTimeout` for
  long steps (Q5). These are config changes gated on load testing.

## UI design (Phase 4)

> **Measured priority (Phase 0):** TTI is API-bound (~2 s render over the API call), so
> the backend phases carry the TTI win. Within Phase 4, the highest-value items are the
> single-flight guard (U7) and the poll guard (U1) — they roughly halve effective
> latency and stop request pile-up. Memoization/virtualization (U3/U5) help poll-time
> re-render churn, not first paint; `summary` payload mode (B6) is a minor win.

- **Single-flight + cancellation (U7):** guard `fetchProjectDetails` so only one request
  is in flight at a time — track the in-flight promise and reuse it, and use an
  `AbortController` to cancel a superseded request on re-fetch/unmount. Removes the
  duplicate concurrent load call (measured ~2× latency amplification).
- **Smart poll (U1, U5):** send `If-None-Match` with the last `ETag`; on `304`, do
  nothing. Otherwise shallow-compare (or hash-compare) before `setComponentState`.
  **Do not start a poll while a request is in flight** (the measured response can exceed
  the 20 s interval); pause polling when the tab is hidden (`document.visibilityState`)
  and consider an interval that backs off toward the observed response time.
- **Split context (U2):** move volatile fields (`isLoading`, `dialogParams`,
  `bootstrapBreakpoint`) into a separate context/provider so a loading toggle doesn't
  re-render layer rows.
- **Memoization (U3):** wrap `LayerRow`, `ModelRow`, `ModelRowMobile` in `React.memo`;
  `useMemo` derived arrays; `useCallback` handlers passed as props.
- **Lazy expansion / virtualization (U5):** render a layer's `models[]` only when
  expanded; introduce windowing (e.g. `react-window`) if list sizes warrant.
- **Parallel fetches (U4):** `Promise.all` the independent GETs in
  `CreateEditImageLayerHelper.js` and `LabelingTool.jsx`.
- **Tiles (U6):** request an overview/thumbnail first; defer full-res second map.

## Configuration

| Config Key | Type | Default | Where | Description |
|---|---|---|---|---|
| `HASTE_METADATA_LOAD_WORKERS` | int | 8 | App Settings / `local.settings.json` | Bounded parallelism for `load_map` fan-out |
| `HASTE_PROJECTDETAILS_CACHE_SECONDS` | int | 15 | App Settings | `Cache-Control: max-age` for `GetProjectDetails` |
| queue `batchSize` | int | 1 → TBD | `host.json` | Concurrent messages per instance (load-test gated) |

## Observability

- Log per-request storage round-trip **count** and total storage time in
  `GetProjectDetails` (proves the O(N)→O(1) win and guards against regression).
- Emit request duration to App Insights; add a synthetic 50-layer project to the perf
  test to track p95 over time.
- Track queue depth and dequeue/poison counts when changing `host.json`.

## Open Questions

- [ ] Does the storage backend (Blob vs Cosmos, via `UnifiedDataLayer`) support a
      server-side predicate for `load_filtered`, or is prefix-scan + in-layer filter
      the best available? Determines how much H3 actually saves on the Blob path.
- [ ] Is the double-serialization (H4) safe to fix in place, or are there existing
      blobs already double-encoded that need a migration/back-compat read path?
- [ ] Acceptable default polling interval / should we move to server-push (SignalR)
      instead of polling for run-status updates?
