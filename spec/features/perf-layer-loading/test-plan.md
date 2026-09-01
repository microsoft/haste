# Test Plan: Image Layer & Model Run Loading Performance

## Strategy

Performance work must be **measured, not asserted**. Every phase compares against the
Phase 0 baseline on a fixed synthetic project. Correctness tests guard that the
refactors preserve behavior (same data, new speed).

## Benchmark fixture

A synthetic project used everywhere in this spec:

- **Small:** 5 layers × 2 models
- **Medium:** 20 layers × 5 models
- **Large (headline):** 50 layers × ~5 models, plus labels + validation per layer

Provide a seed script (`hastelib/tests` helper or a queue-message replay) that
populates the local Docker Compose storage emulator (Azurite) with these shapes.

## Metrics captured (per fixture size)

| Metric | How | Target (Large) |
|---|---|---|
| `GetProjectDetails` p50 / p95 latency | timed API calls (warm) | p95 < 1.5s |
| Storage round-trip count per request | Phase 0 counter log | ≤ ~6 + 2 bounded fan-outs |
| Response payload size | `Content-Length` | tracked; smaller in `summary` mode |
| UI time-to-interactive | DevTools performance trace | p95 < 2s |
| Idle open-project network/CPU over 60s | DevTools, no data change | no full refetch; `304` on poll |

## Baseline capture (Phase 0 — measured 2026-08-03)

Full detail in [results.md](results.md). Captured via `tools/phase0_baseline.py`
(real code, real seeded data, local FS backend).

| Fixture | round-trips | API p50 | API p95 | payload | **UI TTI** |
|---|---|---|---|---|---|
| Small (5×2) | **33** | 0.70 s | 0.71 s | 4.2 KB | 3.10 s |
| Medium (20×5) | **243** | 6.18 s | 6.71 s | 33.2 KB | 12.36 s |
| Large (50×5) | **603** | **20.77 s** | **21.78 s** | 82.8 KB | **40.27 s** |

Round-trips match `3 + L·(2M+2)` exactly. Large breakdown: 301 `load`, 52
`load_all_from_partition` (50 redundant `LABELS` scans = B1), 250 `export` (B2).
API latency measured via `tools/bench_api_http.py`; UI TTI via `tools/ui_bench.cjs`
(Playwright vs the real app). TTI is API-bound (~2 s render over the API call) and the
UI fires the call twice concurrently on load. All numbers are a lower bound (localhost
Azurite, amd64 emulation, Vite dev mode). See [results.md](results.md).

## Correctness / regression tests

### Backend (`hastelib/tests/`)
- `load_map`: returns one entry per key; `None` for missing (parity with old
  per-key `try/except FileNotFoundError`); respects `max_workers`.
- `load_filtered`: returns the same subset the old "load all + Python filter" produced,
  for `imageLayerId` predicate.
- `load_all` with prefix: identical results to prior no-prefix scan for a given
  partition; no cross-partition leakage.
- H4 tolerant read: correctly decodes both legacy double-encoded and new
  single-encoded blobs.
- `BlobServiceClient` reuse: same client instance returned for same conn-string.

### API (`hastefuncapi`)
- `GetProjectDetails` default response is **byte-for-byte equivalent** (post-sort) to
  the pre-refactor response for Small/Medium/Large fixtures (golden-file compare).
- `summary` mode omits `models[]` but keeps counts.
- `includeArtifacts=false` skips artifact expansion, keeps `modelCount`.
- `ETag` stable across identical requests; `If-None-Match` match ⇒ `304` empty body.
- `GenerateProjectStats` parity after the B5 hoist.

### Queue (`hastefuncqueues`)
- Training trigger with `load_filtered` selects the same label project as before.
- `save_batch` persists all items; partial-failure behavior defined and tested.
- With `batchSize`>1: N messages processed, no dropped/duplicated results; poison
  path exercised at `maxDequeueCount`.

### UI (`ui`)
- **Single-flight (U7):** initial project load issues **exactly one** `GetProjectDetails`
  (not two) — assert via `tools/ui_bench.cjs` `getprojectdetails_calls_during_load == 1`
  (production build) and a network spy; a superseded fetch is aborted.
- **Poll guard (U1):** no new poll fires while a request is in flight; assert no
  overlapping `GetProjectDetails` when response time > interval.
- Poll receiving `304` (or byte-identical body) does **not** call `setComponentState`
  (assert via spy/render-count).
- `LayerRow`/`ModelRow` memoized: unchanged props ⇒ no re-render (React Profiler).
- Expanding a layer renders its model rows; collapsed layers render none.
- Edit/labeling helpers issue independent GETs concurrently (`Promise.all`).

## Load test (Phase 3 gate)

- Enqueue a burst (e.g. 100 image/inference messages); compare end-to-end drain time
  and poison count for `batchSize` 1 vs candidate value.
- Confirm no `visibilityTimeout` re-enqueue storms on long-running steps.

## Exit gate

- [ ] Large-fixture targets met and recorded in the baseline table (before/after).
- [ ] All correctness/parity tests green.
- [ ] `docker compose up` runs the full stack with the synthetic project without error.
- [ ] CI (secret-scan, deploy-apps) passes.
