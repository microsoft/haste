# Measured Results

## Contents

- [Post-review Hardening](#post-review-hardening-2026-09-01)
- [Phase 2](#phase-2--core-library-hastelib)
- [Phase 1](#phase-1--measured-after-backend-hot-path)
- [Phase 0](#phase-0-baseline--measured-results)
- [Reproduction](#how-to-reproduce)
- [Targets](#targets-to-beat-from-readmemdsuccess-criteria)
- [Environment](#environment-notes)

> **Metric correction (2026-09-01):** the `HASTE_PERF` counter measures logical
> data-layer method calls, not Azure Storage REST transactions. A partition or keyed
> Blob operation can issue one listing plus many GET requests. Historical `33/243/603`
> and `7` values below are logical calls.

## Post-review hardening (2026-09-01)

Clean synthetic project: 50 layers, 5 models per layer, 20 label records per layer,
10 validation labels per layer. Docker Functions + Azurite, forced-refresh requests,
10 measured iterations after 2 warmups:

| Path | Logical calls | p50 | p95 | Payload |
|---|---:|---:|---:|---:|
| Forced refresh (`Cache-Control: no-cache`) | 7 | **1.85 s** | **2.00 s** | 166.2 KB |
| Fresh process-local cache (`--allow-cache`) | 0 | **9.1 ms** | **12.2 ms** | 166.2 KB |

Correctness check: exactly 50 layers, 250 models, 250 non-null artifact records, and
`validationLabelCount == 10` for every layer. The `<1.5 s` uncached p95 target remains
open. Cache numbers are process-local and do not imply cross-instance coherence.

Production UI bundle against the same API fixture:

| Browser path | TTI | Initial calls | Post-response render | 26 s poll window |
|---|---:|---:|---:|---:|
| Terminal jobs | **2.12 s** | **1** | 58 ms | **0 calls** |
| One active job | **2.27 s** | **1** | 69 ms | **1 call**, HTTP `304` |

The original page loaded Azure Maps control/drawing scripts and styles globally. In the
test environment those four CDN requests blocked `DOMContentLoaded` for about 14 s,
including on the non-map project page. Route-level code splitting plus on-demand Azure
Maps loading reduced the main JS chunk from 1.49 MB to about 120 KB and moved
`DOMContentLoaded` to 68 ms. A map-route browser smoke test confirmed `atlas`, drawing,
and `SwipeMap` are available after the lazy loader runs.

The `<2 s` production TTI target remains open by about 120 ms on the terminal fixture;
the uncached API call (1.93 s in that run) is now the dominant component.

## Phase 2 — Core library (hastelib)

**Date:** 2026-08-03 · **Branch:** `prbatero/feat/performance-improvements-phase2`

Phase 2 removes data-layer waste and adds batch primitives. Delivered:

- **H2 — parallel per-blob downloads** in `load_all_from_partition` / `load_all`
  (blob layer) and `fetch_artifact` through one process-wide bounded executor.
- **H5 — `BlobServiceClient` reuse**: a process-wide `lru_cache`d factory in
  `utils/blob.py` (was created per call in `download_blob_to_tempfile` /
  `read_blob_range`).
- **Batch primitives**: `MetadataProcessor.load_map` (parallel per-key load, perf
  counter propagated into worker threads via `perf.bind`) and `load_filtered`
  (partition scan + in-process predicate), backed by cross-backend regression tests.

**Measured (50×5, Azurite/dev):** `GetProjectDetails` correctness unchanged (50
layers, 250 models/artifacts, counts correct); logical calls remain **7**; latency
**~2.08 s p50 — flat vs Phase 1**.

The Azurite benchmark validates the control flow, not production network performance.
Real Azure concurrency must be tuned and measured under representative request load.

**Net:** Phase 1 removed the sequential logical-call amplification; Phase 2 bounds
aggregate concurrency and improves production I/O behavior. Underlying Blob transactions
remain proportional to the number of records downloaded.

The earlier statement that Phase 2 necessarily makes real Azure sub-second was a
projection, not a measurement, and is superseded by the measured table above.

## Phase 1 — Measured After (backend hot path)

**Date:** 2026-08-03 · **Branch:** `prbatero/feat/performance-improvements-phase1`

Phase 1 loads every metadata type **once per partition** and joins in memory
(`asyncio.gather` for the independent reads), and replaces the 250 per-model
`TRAIN_LABELS` export `exists()` round-trips with **one** blob-name listing + local
SAS URL construction. Same measurement harnesses as Phase 0.

| Fixture | Logical calls | API p50 | UI TTI | | before → after |
|---|---|---|---|---|---|
| small (5×2) | 33 → **7** | 0.70 → **0.20 s** | 3.10 → **2.97 s** | | |
| medium (20×5) | 243 → **7** | 6.18 → **0.84 s** | 12.36 → **3.63 s** | | |
| large (50×5) | 603 → **7** | 20.77 → **2.02 s** | 40.27 → **5.50 s** | | **API 10.3× · TTI 7.3×** |

- **Logical calls are seven** regardless of project size. Blob REST transactions still
  scale with the downloaded records. The seven operations are project plus
  {imagelayer, labels, validation, model, artifacts}
  partition reads + 1 train-labels key listing, the last six run concurrently.
- **`X-Haste-Storage-Ms` (5.5 s) now exceeds `X-Haste-Wall-Ms` (2.0 s)** on large,
  confirming the reads run in parallel (sum of per-call time > wall time).
- The large poll call dropped **36.5 s → 2.05 s**.
- Correctness verified: 50 layers, 5 models each, all 250 artifacts joined,
  `labelProjectCount`/`validationLabelCount` correct, and the `labelsUrl` build path
  confirmed (populates a SAS URL when a train-labels blob exists, else null).
- The after-payload is *larger* (166 KB vs 82 KB — the seed was enriched for the UI
  run), so the latency win is conservative.

**Historical Phase 1 state:** UI TTI (5.5 s) exceeded the API call because the page
fired `GetProjectDetails` twice and did not consume ETags. The post-review hardening
measurements above supersede that state.

---

## Phase 0 Baseline — Measured Results

**Date:** 2026-08-03
**Branch:** `prbatero/feat/performance-improvements`
**Method:** `tools/phase0_baseline.py` — seeds synthetic projects into the real
`local` filesystem backend and replays the exact `GetProjectDetails` read+assemble
sequence ([function_app.py:534-638](../../../api/hastefuncapi/function_app.py#L534-L638))
with `HASTE_PERF` instrumentation on. Models seeded **without** `labelsUrl` (worst-case
N+1 that triggers the per-model `TRAIN_LABELS` export).

### Headline metric — logical data-layer calls per request

| Fixture | Layers × Models | **Logical calls** | Payload | Formula `3 + L·(2M+2)` |
|---|---|---|---|---|
| small | 5 × 2 | **33** | 9.1 KB | 33 ✓ |
| medium | 20 × 5 | **243** | 82.5 KB | 243 ✓ |
| large | 50 × 5 | **603** | 205.8 KB | 603 ✓ |

Logical-call counts match the derived formula, confirming the replay is
faithful to the handler and that cost scales as **O(layers × models)**.

## Per-op breakdown (large, 50 × 5)

| Op | Count | Source |
|---|---|---|
| `load` | 301 | 1 project + 250 per-model `MODEL_ARTIFACTS` (B2) + 50 per-layer `VALIDATION` (B3) |
| `load_all_from_partition` | 52 | 1 imagelayer + 1 model + **50 redundant full `LABELS` scans** (B1 — should be 1) |
| `export` | 250 | per-model `TRAIN_LABELS` export (B2) |
| **total** | **603** | |

**B1 is quantified:** 50 of the 52 partition scans are the identical full `LABELS`
download re-run once per layer. **B2 is quantified:** 500 of 603 round-trips (83%) are
the per-model artifact + labels-export pair.

## Latency — MEASURED against the real API (Docker + Azurite blob backend)

Captured via `tools/bench_api_http.py` against the running stack (compose overlay
`docker/docker-compose.perf.yml`, `HASTE_PERF=true`, `blob` backend on Azurite),
after seeding each project into Azurite. End-to-end `GetProjectDetails?includeModels=True`:

| Fixture | **latency p50** | latency p95 | storage calls | storage time p50 | payload | per-call cost |
|---|---|---|---|---|---|---|
| small (5×2) | **0.70 s** | 0.71 s | 33 | 0.28 s | 4.2 KB | ~8.5 ms/call |
| medium (20×5) | **6.18 s** | 6.71 s | 243 | 3.05 s | 33.2 KB | ~12.5 ms/call |
| large (50×5) | **20.77 s** | 21.78 s | 603 | 13.39 s | 82.8 KB | ~22 ms/call |

**A single large-project load takes ~21 seconds** — and this is a *localhost* emulator;
real Azure Blob has higher per-op latency, so production is worse. Storage accounts for
~65% of wall time (13.4 s of 20.8 s); the rest is Python serialization, the double-JSON
deserialize (H4), and per-blob client creation inside the blob layer.

**B1 is super-linear:** per-call cost climbs 8.5 → 12.5 → 22 ms as the partition grows,
because each of the 50 redundant full-`LABELS` partition scans lists + downloads *every*
label blob, and that set grows with the project. So the redundant scans cost more the
bigger the project gets — compounding the O(layers × models) round-trip growth.

For reference, the local-FS replay wall (no network, relative floor only) was
6.7 / 51.0 / 356.5 ms for small / medium / large.

## Browser-side (UI) baseline — MEASURED (Playwright vs the real React app)

Captured via `tools/ui_bench.cjs` driving the real UI (swa-cli emulator in Docker)
with Playwright. The cheap auth/user bootstrap is mocked (crafted SWA admin cookie +
route interception of `/.auth/me`, `GetUserById`, `PutUser`); **`GetProjectDetails`
hits the real API**. TTI = navigation → first image-layer row visible in the DOM.

| Fixture | **TTI** (open → layers) | initial `GetProjectDetails` | GPD calls on load | 20 s poll |
|---|---|---|---|---|
| small (5×2) | 3.10 s | 1.27 s | 2 | (interval not reached) |
| medium (20×5) | 12.36 s | 10.40 s | 2 | 1 call, 6.20 s |
| large (50×5) | **40.27 s** | 38.44 s | 2 | 1 call, **36.50 s** |

**TTI is API-bound:** it tracks the `GetProjectDetails` duration almost exactly (large
40.3 s TTI vs 38.4 s call — only ~2 s of render). So the layer-loading fix is
fundamentally the backend fix; UI work reduces the *amplifiers* below.

Two UI-specific amplifiers the browser run exposed:
- **Duplicate concurrent fetch (U1-adjacent):** the page issues `GetProjectDetails`
  **twice concurrently** on load (React StrictMode in dev + no request dedup). The two
  603-round-trip requests contend, so browser-observed latency is **~2× the isolated
  API call** (large: 38.4 s browser vs 20.8 s isolated `curl`). Production build drops
  the StrictMode double, but the absence of dedup/caching is real.
- **Poll re-does everything (U1):** the 20 s poll fires a fresh full
  `GetProjectDetails` (large poll call = 36.5 s), re-incurring all 603 round-trips and
  re-rendering the whole tree (no memoization, monolithic context). Because the
  response (~21–38 s) is **longer than the 20 s interval**, polls overlap and pile up.

**Caveats (inflate absolute numbers, not the structural findings):** UI ran under Vite
**dev mode** (unminified + StrictMode double-invoke); the API image is amd64 emulated on
Apple Silicon; storage is a localhost Azurite emulator. A production build + real Azure
would shift the constants but not the O(layers × models) scaling or the amplifiers.
- To capture TTI/poll cost precisely once the stack is up: Chrome DevTools Performance
  trace on the project page; `Server-Timing` (now emitted by the API) surfaces
  server storage time directly in the Network panel.

## How to reproduce

```bash
# Headline logical-call baseline (no infra needed):
PYTHONPATH=hastelib/src python3 \
  spec/features/perf-layer-loading/tools/phase0_baseline.py

# Real latency (requires running stack + HASTE_PERF=true on the API + seeded project):
METADATA_STORAGE_TYPE=local DATA_PATH=/tmp/haste-bench PYTHONPATH=hastelib/src \
  python3 spec/features/perf-layer-loading/tools/seed_synthetic_project.py \
    --project-id <guid> --layers 50 --models 5
python3 spec/features/perf-layer-loading/tools/bench_api_http.py \
  --base-url http://localhost:7071/api --project-id <guid> --repeats 30
```

## Targets to beat (from [README.md](README.md#success-criteria))

| Metric | Baseline (large, measured) | Target |
|---|---|---|
| Logical calls / request | **603** | 7 |
| API p50 / p95 latency | **20.8 s / 21.8 s** (Azurite) | < 1.5 s |
| Payload (default shape) | 82.8 KB | smaller via `summary` mode |

## Environment notes

- Backend: Azurite blob emulator on `localhost` (compose). Real Azure Blob per-op
  latency is higher, so these numbers are a **lower bound** on production.
- Host: Docker Desktop on Apple Silicon; the amd64 API image runs emulated, inflating
  the non-storage (CPU) portion somewhat. Logical-call counts are hardware-independent;
  use Azure metrics for actual transaction counts.
- Reproduce: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.perf.yml
  up -d hastefuncapi api-proxy`, seed via `seed_synthetic_project.py` inside the
  `hastefuncapi` container, then run `bench_api_http.py` from the host.
