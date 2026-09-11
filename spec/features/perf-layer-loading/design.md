# Technical Design: Image Layer & Model Run Loading Performance

## Overview

Collapse `GetProjectDetails` from hundreds of sequential logical data-layer calls to
seven top-level operations. Preserve storage-key semantics for legacy records, overlap
independent I/O behind one process-wide concurrency budget, and reuse Azure SDK clients.
A bounded process-local cache deduplicates concurrent requests and serves fresh ETag
checks without storage work. Underlying Blob GET transactions still scale with the
records returned; a materialized project view would be required to make those constant.

## Contents

- [Architecture](#architecture)
- [API Design](#api-design)
- [Internal Interfaces](#internal-interfaces-hastegeo)
- [Caching](#caching)
- [UI Design](#ui-design-phase-4)
- [Configuration](#configuration)
- [Observability](#observability)

## Architecture

```
┌──────────────┐   GetProjectDetails    ┌────────────────────┐   1 read / type   ┌──────────────┐
│   React UI   │───────────────────────▶│   hastefuncapi      │──────────────────▶│ Blob / Cosmos │
│  Project.jsx │  (single-flight/ETag)  │  GetProjectDetails   │ keyed batch reads  │  data layer  │
└──────────────┘                        └─────────┬──────────┘                    └──────────────┘
      ▲ smart poll (304 fast-path)                │ uses
      │                                  ┌─────────▼──────────┐
      └── active-job-only polling         │ ProjectDetailsProc. │ load_map() / exact
                     │ + shared I/O budget │ metadata prefixes
                                         └────────────────────┘
```

## API Design

### `GET /api/GetProjectDetails` — reworked internals (contract unchanged by default)

The response shape remains unchanged. The only implemented query parameter is:

| Param | Type | Default | Effect |
|---|---|---|---|
| `includeModels` | bool | `false` | Include models, artifacts, and train-label URLs. |

`summary` and `includeArtifacts` remain deferred. Do not send them until their response
contracts are implemented and tested.

Response headers are `ETag`, `Cache-Control: private, max-age=<ttl>`, and
`X-Haste-Cache`. A matching `If-None-Match` returns `304` with an empty body. Request
`Cache-Control: no-cache` or `max-age=0` forces a storage refresh before comparison.

### Reworked handler logic (replaces [function_app.py:534-638](../../../api/hastefuncapi/function_app.py#L534-L638))

```python
project = await ProjectDetailsProcessor(project_id, config).load(include_models)
payload = json.dumps(project)
etag = sha256(payload.encode()).hexdigest()
```

`ProjectDetailsProcessor` loads the project first as the `404` gate, loads layers,
labels, and models concurrently, then uses keyed `load_map` calls for validation and
artifacts. Keyed maps preserve the old storage-key joins even when legacy document
bodies omit optional `imageLayerId` or `modelId` fields.

## Internal Interfaces (hastegeo)

| Module | Change | Signature | Purpose |
|---|---|---|---|
| `core/processors/project_details.py` | **new** | `ProjectDetailsProcessor.load(include_models)` | Own storage orchestration and pure response assembly. |
| `core/processors/metadata.py` | **new** | `load_map(keys, max_workers=None)` | Prefer one native Cosmos/PostgreSQL query; otherwise use bounded keyed loads. |
| `core/processors/metadata.py` | **new** | `load_filtered(predicate)` | Explicit client-side partition scan and property filter; not a server-side optimization. |
| `core/utils/parallel.py` | **new** | `parallel_map(...)` | One process-wide worker budget shared by requests and storage operations. |
| `core/utils/async_cache.py` | **new** | `AsyncTTLCache` | Bounded TTL cache with per-key single-flight loading. |
| `core/utils/blob.py` | **fix** | `get_blob_service_client(...)` | Reuse top-level clients and connection pools by credential target. |
| Blob/local/Data Lake/Cosmos layers | **fix** | exact metadata matching | Longest known type wins, so `model` cannot consume `model_catalog`. |
| Blob artifact storage | **fix** | atomic bounded download | Validate paths and replace temporary files only after successful download. |

## Caching

The cache key is `(projectId, includeModels)`. It stores only successful serialized
responses, shares an in-flight load among concurrent callers, and evicts least-recently
used entries beyond the configured bound. It is process-local and therefore does not
provide cross-instance coherence. After the TTL, active-job polling refreshes storage.

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

- **Single-flight + cancellation (U7, implemented):** one keyed in-flight promise is
  shared; a different project or real unmount aborts superseded work.
- **Smart poll (U1, implemented):** send `If-None-Match`; return before state updates on
  `304`; do not poll while hidden, in flight, or when all known jobs are terminal.
- **Route assets (implemented):** route modules use `React.lazy`; Azure Maps control,
  drawing, and swipe assets load in order only before a map-dependent route mounts.
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
| `HASTE_BLOB_DOWNLOAD_WORKERS` | int (1–64) | 16 | App Settings | Process-wide blocking I/O thread budget. |
| `HASTE_METADATA_LOAD_WORKERS` | int (1–64) | 8 | App Settings | Per-map limit within the global I/O budget. |
| `HASTE_ARTIFACT_DOWNLOAD_WORKERS` | int (1–64) | 8 | App Settings | Per-artifact limit within the global budget. |
| `HASTE_PROJECTDETAILS_CACHE_SECONDS` | int (0–300) | 15 | App Settings | Process-local freshness and response `max-age`. |
| `HASTE_PROJECTDETAILS_CACHE_ENTRIES` | int (1–512) | 64 | App Settings | Maximum process-local project response entries. |
| queue `batchSize` | int | 1 → TBD | `host.json` | Concurrent messages per instance (load-test gated) |

## Observability

- Log logical data-layer call count/time and cache hit/miss in `GetProjectDetails`.
  These metrics do not count Azure REST transactions; use Azure Storage metrics or SDK
  pipeline instrumentation for transaction/cost analysis.
- Emit request duration to App Insights; add a synthetic 50-layer project to the perf
  test to track p95 over time.
- Track queue depth and dequeue/poison counts when changing `host.json`.

## Open Questions

- [x] `load_filtered` is an explicit partition-scan fallback and does not reduce
  transferred records. A future backend query API is required for server filtering.
- [ ] Is the double-serialization (H4) safe to fix in place, or are there existing
      blobs already double-encoded that need a migration/back-compat read path?
      *(Partially answered 2026-08-20: legacy double-encoded blobs must be assumed, so
      Phase 2 shipped a tolerant read (`_read_blob_content` parses twice when the first
      parse yields a string) and deferred the save-side fix behind a migration. New
      constraint from the data-publishing merge: `save()` now stamps `_index_metadata`
      blob metadata, which any save-path rewrite must preserve.)*
- [ ] Acceptable default polling interval / should we move to server-push (SignalR)
      instead of polling for run-status updates?
