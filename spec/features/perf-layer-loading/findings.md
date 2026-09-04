# Findings: Verified Performance Bottlenecks

## Contents

- [Cost Model](#cost-model-why-it-scales)
- [HTTP API](#backend--apihastefuncapifunction_apppy)
- [Core Library](#backend--hastelibsrchastegeocore)
- [Queue Workers](#queue--apihastefuncqueuesfunction_apppy)
- [UI](#ui--uisrc)
- [Measured Priority](#measured-priority-adjustments-phase-0)

> **Baseline terminology:** the Phase 0 counter records logical data-layer calls, not
> Azure REST transactions. The N+1 findings and latency measurements remain valid, but
> one partition call can contain a listing plus many Blob downloads.

> **Implementation status (2026-09-01):** B1–B5, B7, H2, and H5 are addressed on the
> cumulative branch. B6, server-side filtering, a materialized project view, and queue
> configuration remain open. UI single-flight, ETag handling, in-flight/visibility
> guards, and active-job-only polling are implemented.

Each finding was confirmed by reading the referenced code. Severity reflects impact
on the reported symptom (slow layer/run loading that scales with layer count).

## Cost model (why it scales)

For a project with **L** image layers and an average of **M** models per layer, the
`GetProjectDetails?includeModels=True` request currently issues approximately:

```
3                      (project + image_layers + all-models partition reads)
+ L × 1                (LABELS full-partition scan — once PER layer, see B1)
+ L × 1                (VALIDATION load per layer)
+ L × M × 2            (MODEL_ARTIFACTS load + TRAIN_LABELS export per model)
= 3 + 2L + 2LM  sequential, blocking logical data-layer calls
```

For L=50, M=5 that is **~603 sequential round-trips**, each an `await asyncio.to_thread(...)`
that blocks the next. None are parallelized. The target is a **small constant** (≤ ~6).

---

## Backend — `api/hastefuncapi/function_app.py`

### B1 — CRITICAL: full LABELS partition scan re-run once per layer
[function_app.py:594-599](../../../api/hastefuncapi/function_app.py#L594-L599)

Inside `for image_layer in image_layers:` the code calls
`MetadataProcessor(LABELS, partition_key=project_id).load_all_from_partition`. The call
takes **no per-layer argument** — it returns the identical full label set every
iteration, then filters in Python by `imageLayerId`. This is a pure redundancy bug:
the download is repeated L times when it should happen **once** before the loop.
`load_all_from_partition` downloads and deserializes every label blob in the
partition, so this is L full-partition downloads.

**Measured (Phase 0):** per-round-trip cost is **super-linear** — 8.5 → 12.5 → 22 ms
as the partition grows (small → medium → large), because each redundant scan lists +
downloads an ever-larger label set. So B1 costs *more* the bigger the project, on top
of running L times. See [results.md](results.md).

### B2 — CRITICAL: per-model artifact + labels loads, sequential
[function_app.py:565-591](../../../api/hastefuncapi/function_app.py#L565-L591)

For every model of every layer, two sequential awaits: `MODEL_ARTIFACTS.load(modelId)`
and `TRAIN_LABELS.export(modelId)`. That is `L × M × 2` blocking round-trips executed
one at a time. This is the single largest contributor for model-heavy projects.

### B3 — HIGH: per-layer VALIDATION load, sequential
[function_app.py:621-632](../../../api/hastefuncapi/function_app.py#L621-L632)

`VALIDATION.load(image_layer_id)` per layer, sequential — `L` more blocking round-trips
that could be one batched/parallel read.

### B4 — HIGH: no parallelism anywhere in the handler
The handler uses `await asyncio.to_thread(...)` for each I/O but never
`asyncio.gather`. Even the independent initial loads (project → image_layers →
all-models) are chained. Every storage call waits for the previous one.

### B5 — HIGH: same N+1 repeated in `GenerateProjectStats`
[function_app.py:2602-2624](../../../api/hastefuncapi/function_app.py#L2602-L2624)

The identical per-layer `LABELS.load_all_from_partition` pattern exists in the stats
path, so dashboards/stats regeneration degrade the same way.

### B6 — MEDIUM: unbounded response, no pagination
[function_app.py:638](../../../api/hastefuncapi/function_app.py#L638) returns the entire
nested project (`imageLayer[].models[].artifacts`) in one payload. Serialization and
transfer grow with total model count; there is no page/limit and no lightweight
"summary" shape for the initial list render.

### B7 — MEDIUM: no HTTP caching on list/detail endpoints
`GetModelArtifact` sets `Cache-Control`/`ETag`, but `GetProjectDetails`,
`GetProjectStats`, `GetLayerModelsDetails`, `GetLayerDetailView` set none — every poll
is a full recompute + full transfer even when nothing changed.

---

## Backend — `hastelib/src/hastegeo/`

### H1 — HIGH: `load_all` scans the whole container, no prefix
[data_layer/azure_blob_storage_data_layer.py:268-323](../../../hastelib/src/hastegeo/core/data_layer/azure_blob_storage_data_layer.py#L268-L323)

`walk_blobs()` is called with **no `name_starts_with`**, listing the entire container,
then filtering in Python. `load_all_from_partition` does pass a prefix (good), but
`load_all` does not. All matched blobs are then fully downloaded even when only counts
/ metadata are needed.

### H2 — HIGH: sequential per-blob download in listing + artifact fetch
[artifact_storage/azure_blob_artifact_storage.py:179-187](../../../hastelib/src/hastegeo/core/artifact_storage/azure_blob_artifact_storage.py#L179-L187)
and the download loops in `load_all` / `load_all_from_partition`. Each blob is
downloaded and read to completion before the next starts — `N` files ⇒ `N ×` latency.
A bounded `ThreadPoolExecutor` would collapse this to roughly one round-trip of
latency.

### H3 — HIGH: no filtered query — everything filtered in Python
`MetadataProcessor.load_all_from_partition` has no `imageLayerId`/predicate parameter,
forcing callers (B1, and the queue in Q2) to pull the whole partition and filter
in-process. A `load_filtered(...)` method would let callers request only what they need.

### H4 — MEDIUM: double JSON deserialization
[data_layer/azure_blob_storage_data_layer.py:254-259](../../../hastelib/src/hastegeo/core/data_layer/azure_blob_storage_data_layer.py#L254-L259)
(and 3 sibling paths) — `json.loads` result is `json.loads`-ed again for
projects/image_layers because they were double-serialized on save. CPU cost on every
read; the real fix is single-serialize on write, then drop the re-parse.

### H5 — MEDIUM: `BlobServiceClient` created per call
[core/blob.py:79-81, 150-151](../../../hastelib/src/hastegeo/core/blob.py#L79-L81) —
`BlobServiceClient.from_connection_string(...)` on every `download_blob_to_tempfile` /
`read_blob_range` call; no module-level reuse, so credential parse + connection setup
repeat. Same theme: `MetadataProcessor`/`UnifiedDataLayer` are re-instantiated dozens
of times per request/message rather than reused.

### H6 — MEDIUM: no caching layer anywhere except `footprints.get_latest_release`
[core/utils/footprints.py:155](../../../hastelib/src/hastegeo/core/utils/footprints.py#L155)
is the only `lru_cache` in the core library. There is no request-scoped memoization,
so `load_and_combine_sub_data_types` and similar re-fetch identical data within a
single request.

---

## Queue — `api/hastefuncqueues/function_app.py`

### Q1 — HIGH: `batchSize: 1`, `maxDequeueCount: 1`
[host.json](../../../api/hastefuncqueues/host.json) processes one message per instance
and dead-letters after a single failure (no retry). Throughput depends entirely on
instance scale-out; a transient error poisons the message immediately.

### Q2 — HIGH: N+1 label lookup in training trigger
[function_app.py:354-367](../../../api/hastefuncqueues/function_app.py#L354-L367) —
`LABELS.load_all_from_partition` then Python `next(...)` filter; should use H3's
filtered load.

### Q3 — MEDIUM: independent loads not parallelized
Inference trigger loads image layer then experiment config sequentially
([function_app.py:695-712](../../../api/hastefuncqueues/function_app.py#L695-L712));
image-processing trigger does store-artifact then get-URL sequentially. `asyncio.gather`
would halve these.

### Q4 — MEDIUM: 3–5 sequential `MetadataProcessor.save` calls per message, no batching.
Every trigger re-instantiates `MetadataProcessor` several times and awaits each save
serially. A `save_batch` would cut round-trips.

### Q5 — LOW: `visibilityTimeout: 30s` risks re-enqueue for slow checkpoints; consider
raising or extending visibility on long steps.

---

## UI — `ui/src/`

### U1 — CRITICAL: 20s poll refetches the entire project incl. all models
[Project.jsx:149-157](../../../ui/src/Components/Project.jsx#L149-L157) →
[Project.jsx:102-147](../../../ui/src/Components/Project.jsx#L102-L147) calls
`GetProjectDetails?includeModels=True` every 20s, always `setComponentState(...)` even
when data is unchanged. This drives B1–B4 repeatedly and re-renders the whole tree on
a timer.

**Measured (Phase 0):** the large-project response is **~21–38 s — longer than the 20 s
poll interval**, so a new poll fires before the previous one returns and overlapping
603-round-trip requests pile up on the backend. The poll must not fire while a request
is in flight (single-flight guard) and/or the interval must adapt to response time.

### U7 — HIGH (new, measured): duplicate concurrent `GetProjectDetails` on load
Playwright observed **two concurrent** `GetProjectDetails` calls on the initial project
load, so browser-observed latency is ~2× the isolated API call (large: ~38 s vs 20.8 s).
Dev-mode React StrictMode double-invokes effects, but the root cause that survives a
production build is the **absence of in-flight de-duplication / request cancellation**:
[Project.jsx:102-147](../../../ui/src/Components/Project.jsx#L102-L147) has no
single-flight guard or `AbortController`, so overlapping mounts/effects/polls each issue
a full request. Fix: dedupe in-flight requests and abort superseded ones.

### U2 — HIGH: monolithic `AppContext` → broad re-renders
[AppContext.jsx:266-281](../../../ui/src/AppContext.jsx#L266-L281) — a single
`appParams` object (loading flag, dialog, breakpoint, …) is consumed by ~38
components. Any `setIsLoading` (fired by every poll) re-renders all of them.

### U3 — HIGH: no memoization
No `React.memo` / `useMemo` / `useCallback` anywhere under `ui/src/Components/`. Every
parent render re-renders all `LayerRow` / `ModelRow` children with freshly-created prop
objects.

### U4 — MEDIUM: sequential independent API calls
[CreateEditImageLayerHelper.js:28-37](../../../ui/src/Components/CreateEditImageLayerHelper.js#L28-L37)
and [LabelingTool.jsx:174-181](../../../ui/src/Components/LabelingTool/LabelingTool.jsx#L174-L181)
`await` two independent GETs in series; should be `Promise.all`.

### U5 — MEDIUM: no change detection on poll; eager model-row rendering on expand;
no virtualization for large layer/model lists
([Project.jsx:193-228](../../../ui/src/Components/Project.jsx#L193-L228),
[ProjectManagement/LayerRow.jsx:359-404](../../../ui/src/Components/ProjectManagement/LayerRow.jsx#L359-L404)).

### U6 — MEDIUM-LOW: Visualizer requests full-res pre+post tiles eagerly with no
overview/thumbnail
([Visualizer/Visualizer.jsx:315-345](../../../ui/src/Components/Visualizer/Visualizer.jsx#L315-L345)).

## Measured priority adjustments (Phase 0)

The browser baseline reshuffles a few priorities relative to first estimates:

- **Backend-first is strongly validated.** UI time-to-interactive is **API-bound**:
  TTI ≈ the `GetProjectDetails` duration + only ~2 s of render (large: 40.3 s TTI vs
  38.4 s call). So Phase 1/2 (backend) captures the overwhelming majority of the TTI
  win; no UI change can hide a 20 s API call.
- **U7 + poll-overlap (U1) rise in priority** — they roughly *double* effective latency
  and pile requests on the backend. Cheap to fix (single-flight guard), high impact.
- **Render-side items (U3 memoization, U5 virtualization) drop for TTI** — with only
  ~2 s of render at 50 layers, they matter for *poll-time smoothness / re-render churn*,
  not first paint. Still worth doing, but not the TTI lever.
- **B6 payload is minor** — the large default payload is only ~83 KB; `summary` mode is
  a nice-to-have, not a latency driver. Round-trip count, not payload size, dominates.
