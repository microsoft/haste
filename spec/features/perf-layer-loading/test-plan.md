# Test Plan: Image Layer & Model Run Loading Performance

## Contents

- [Strategy](#strategy)
- [Benchmark Fixture](#benchmark-fixture)
- [Metrics](#metrics-captured-per-fixture-size)
- [Baseline](#baseline-capture-phase-0--measured-2026-08-03)
- [Regression Tests](#correctness--regression-tests)
- [Load Test](#load-test-phase-3-gate)
- [Exit Gate](#exit-gate)

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
| Uncached `GetProjectDetails` p50 / p95 | HTTP harness sends `Cache-Control: no-cache` | p95 < 1.5s |
| Warm process-cache p50 / p95 | HTTP harness with `--allow-cache` | tracked separately |
| Logical data-layer calls | `HASTE_PERF` headers | 7; not an Azure transaction metric |
| Response payload size | `Content-Length` | tracked; smaller in `summary` mode |
| UI time-to-interactive | DevTools performance trace | p95 < 2s |
| Idle open-project network/CPU over 60s | DevTools, no data change | no full refetch; `304` on poll |

## Baseline capture (Phase 0 — measured 2026-08-03)

Full detail in [results.md](results.md). Captured via `tools/phase0_baseline.py`
(real code, real seeded data, local FS backend).

| Fixture | logical calls | API p50 | API p95 | payload | **UI TTI** |
|---|---|---|---|---|---|
| Small (5×2) | **33** | 0.70 s | 0.71 s | 4.2 KB | 3.10 s |
| Medium (20×5) | **243** | 6.18 s | 6.71 s | 33.2 KB | 12.36 s |
| Large (50×5) | **603** | **20.77 s** | **21.78 s** | 82.8 KB | **40.27 s** |

Logical calls match `3 + L·(2M+2)` exactly. Large breakdown: 301 `load`, 52
`load_all_from_partition` (50 redundant `LABELS` scans = B1), 250 `export` (B2).
API latency measured via `tools/bench_api_http.py`; UI TTI via `tools/ui_bench.cjs`
(Playwright vs the real app). TTI is API-bound (~2 s render over the API call) and the
UI fires the call twice concurrently on load. All numbers are a lower bound (localhost
Azurite, amd64 emulation, Vite dev mode). See [results.md](results.md).

## Correctness / regression tests

### Backend (`hastelib/tests/`)
- [x] `load_map`: duplicate/missing keys, worker bounds, native query and fallback paths.
- [x] `load_filtered`: non-empty predicates and missing-field semantics.
- [x] Exact metadata matching and partition isolation across file/blob/list paths.
- [x] H4 tolerant read for legacy double-encoded and current JSON.
- [x] `BlobServiceClient` reuse by connection target.
- [x] Shared executor aggregate cap, ordering, nesting, cancellation, and exceptions.
- [x] Atomic artifact download, traversal rejection, and partial-file cleanup.
- [x] Cosmos, Data Lake, PostgreSQL, Blob, and local read-contract coverage.

### API (`hastefuncapi`)
- [x] `GetProjectDetails` response assembly is byte-for-byte checked against a complete
  expected fixture; a real local-storage test covers legacy key-only related records.
- [ ] Deferred: `summary` mode omits `models[]` but keeps counts.
- [ ] Deferred: `includeArtifacts=false` skips artifact expansion.
- [x] ETag/304, weak/list matching, cache hit/miss, refresh, failure retry, and keying.
- [x] `GenerateProjectStats` loads labels once and reports zero for unlabeled layers.

### Queue (`hastefuncqueues`)
- Training trigger with `load_filtered` selects the same label project as before.
- `save_batch` persists all items; partial-failure behavior defined and tested.
- With `batchSize`>1: N messages processed, no dropped/duplicated results; poison
  path exercised at `maxDequeueCount`.

### UI (`ui`)
- [x] **Single-flight (U7):** utility covers dedupe, supersession, abort, and retry;
  browser benchmark remains the integration proof for exactly one initial request.
- [x] Poll guard checks visibility, in-flight state, and active jobs.
- [x] HTTP helper handles `304` without parsing a body; component returns before state
  update.
- [x] Production browser: one initial call, zero terminal-project polls over 26 s.
- [x] Active browser: one conditional poll at 20 s, returning `304` without overlap.
- [x] Map-route smoke test: lazy loader provides `atlas`, drawing, and `SwipeMap`.
- [x] Route splitting: main JS 1.49 MB → about 120 KB; Azure Maps CDN assets no longer block
  non-map routes.
- `LayerRow`/`ModelRow` memoized: unchanged props ⇒ no re-render (React Profiler).
- Expanding a layer renders its model rows; collapsed layers render none.
- Edit/labeling helpers issue independent GETs concurrently (`Promise.all`).

## Load test (Phase 3 gate)

- Enqueue a burst (e.g. 100 image/inference messages); compare end-to-end drain time
  and poison count for `batchSize` 1 vs candidate value.
- Confirm no `visibilityTimeout` re-enqueue storms on long-running steps.

## Exit gate

### Current Validation (2026-09-01)

- Focused regression matrix and final suite counts are refreshed during the final
  validation pass.
- New performance core modules have 100% statement and branch coverage.
- Performance-stack API suite: **50 passed**; two server-managed-field cases are
  owned by the independent security PR. Queue suite: **6 passed**.
  UI suite: **121 passed**; production build passes.
- New UI utilities: 100% line, branch, and function coverage.
- Full `hastelib` suite: **581 passed**. The stale `ArtifactProcessor.zip` test was
  replaced with an isolated test of the current fetch delegation contract.
- UI production build passes. Changed UI files have zero ESLint diagnostics; the
  repository-wide lint command remains red from unrelated existing files.
- Clean 50×5 HTTP fixture: 50 layers, 250 models/artifacts, correct validation counts;
  uncached 1.85 s p50 / 2.00 s p95, warm-cache 9.1 ms / 12.2 ms.
- Production project page: 2.12 s TTI, one initial request, 58 ms post-response render,
  and zero terminal-project polls during 26 seconds. Target remains open.

- [ ] Large-fixture targets met and recorded in the baseline table (before/after).
- [x] Feature-specific correctness/parity tests green.
- [ ] `docker compose up` runs the full stack with the synthetic project without error.
- [ ] CI (secret-scan, deploy-apps) passes.
