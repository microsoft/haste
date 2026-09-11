# Execution Plan: Image Layer & Model Run Loading Performance

Sequenced by impact-per-risk. Phase 0 establishes a baseline so every later phase is
measured, not guessed. Backend before UI: the backend N+1 is the dominant cost and its
fixes are transparent to the UI. Each phase is independently shippable.

## Contents

- [Phase 0: Baseline and Instrumentation](#phase-0-baseline--instrumentation--done-2026-08-03)
- [Phase 1: Backend API Hot Path](#phase-1-backend-api-hot-path-hastefuncapi--highest-roi)
- [Phase 2: Core Library](#phase-2-core-library-hastelib--enables-phase-1-batchfilter)
- [Phase 3: Queue Workers](#phase-3-queue-workers-hastefuncqueues--throughput)
- [Phase 4: UI](#phase-4-ui-uisrc--perceived-performance)
- [Phase 5: Integration and Validation](#phase-5-integration--validation)
- [Milestones](#milestones)
- [Agent Summary](#agent-summary)
- [Open Questions](#open-questions)

## Phase 0: Baseline & Instrumentation — DONE (2026-08-03)

**Goal:** Make the problem measurable before changing it.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Add opt-in logical data-layer counter + timing (`hastelib/.../utils/perf.py`, wired into `MetadataProcessor` reads + `GetProjectDetails` via `HASTE_PERF`) | `backend-dev` | — | B1–B4 | **done** |
| Seed script for synthetic L×M project (`tools/seed_synthetic_project.py`) | `backend-dev` | — | cost-model | **done** |
| Capture baseline data-layer calls + payload (`tools/phase0_baseline.py` → `results.md`) | `backend-dev` | above | success-criteria | **done** |
| HTTP latency harness for running stack (`tools/bench_api_http.py`) | `backend-dev` | above | success-criteria | **done** |
| Capture real API p50/p95 latency against running stack (Docker + Azurite) | `backend-dev` | stack up + seed | success-criteria | **done** |
| Compose overlay + reproducible run (`docker/docker-compose.perf.yml`) | `backend-dev` | — | — | **done** |
| Record UI time-to-interactive + poll cost (Playwright, `tools/ui_bench.cjs`) | `ui` | stack up | U1 | **done** |

**Exit Criteria:**
- [x] Baseline logical calls (33 / 243 / **603**) + payload captured in
      [results.md](results.md) and `test-plan.md`; per-op breakdown quantifies B1/B2.
- [x] Real API latency captured (large **20.8 s p50 / 21.8 s p95** on Azurite;
      storage = 13.4 s of that). Confirms the reported symptom.
- [x] Browser-side UI TTI captured (large **40.3 s**; API-bound + fired twice
      concurrently; 20 s poll re-does the full call). Phase 0 complete.

## Phase 1: Backend API hot path (`hastefuncapi`) — highest ROI

**Goal:** Collapse `GetProjectDetails` to a constant number of storage reads. No API
contract change; UI untouched.

Implemented on branch `prbatero/feat/performance-improvements-phase1`.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Hoist `LABELS.load_all_from_partition` out of the layer loop (load once) | `backend-dev` | P0 | B1 | **done** |
| Parallelize top-level reads (project/layers/models/labels) with `asyncio.gather` | `backend-dev` | P0 | B4 | **done** |
| Batch per-model artifacts with keyed `load_map` + `labelsUrl` with one `list_keys` | `backend-dev` | Ph2 | B2 | **done** |
| Batch per-layer VALIDATION with keyed `load_map` | `backend-dev` | Ph2 | B3 | **done** |
| Apply the same hoist to `GenerateProjectStats` | `backend-dev` | B1 | B5 | **done** |
| Add bounded process-local single-flight cache + `ETag`/`304` handling | `backend-dev` | — | B7 | **done** |
| Add optional `summary` / `includeArtifacts=false` response modes | `backend-dev` | above | B6 | deferred (payload minor per Phase 0 — see findings); if revived, build on the publishing feature's `load_page`/`_index_metadata` metadata-indexed listing rather than a new listing path |

> **Design note:** the final implementation uses keyed `load_map` for artifacts and
> validation, preserving legacy storage-key joins. Blob performs bounded per-key GETs;
> Cosmos and PostgreSQL issue one native query per map. The seven-call count is a
> logical data-layer metric, not an Azure transaction count.

**Exit Criteria:**
- [x] Logical data-layer calls for a 50×5 project drop from **603 → 7**.
- [ ] Uncached `GetProjectDetails` is **1.85 s p50 / 2.00 s p95** on the clean
      50×5 Azurite fixture; the `<1.5 s p95` target is not yet met.
- [x] Fresh process-local cache hits are **9.1 ms p50 / 12.2 ms p95** and perform
      zero logical data-layer calls.
- [x] Existing UI still works unchanged (contract preserved; verified via UI bench —
      TTI 40.3 s → 5.5 s). See [results.md](results.md).

## Phase 2: Core library (`hastelib`) — enables Phase 1 batch/filter

**Goal:** Give the API layer the primitives it needs and remove data-layer waste.
(Ships alongside Phase 1.)

> **Done in Phase 1:** added `list_identifiers` (metadata-only, no-download listing)
> to the abstract/blob/local-FS/unified layers, `MetadataProcessor.list_keys` +
> `build_url`, and a `check_exists=False` fast path on `get_file_remote_path` — these
> are what let B2 drop the export N+1. `load_map`/`load_filtered`, the `load_all`
> prefix fix (H1), parallel download loops (H2), double-serialize fix (H4), and
> `BlobServiceClient` reuse (H5) remain for a dedicated Phase 2 pass.

Implemented on branch `prbatero/feat/performance-improvements-phase2`.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Add `MetadataProcessor.load_map(keys, max_workers)` with native Cosmos/PostgreSQL queries and bounded fallback | `backend-dev` | — | H2 | **done** |
| Add `MetadataProcessor.load_filtered(predicate)` | `backend-dev` | — | H3 | **done** |
| Parallelize download loops through one process-wide bounded executor; make artifact files atomic | `backend-dev` | — | H2 | **done** |
| Reuse module-level `BlobServiceClient` keyed by connection target | `backend-dev` | — | H5 | **done** |
| Unit, contract, API, and local-storage regression tests | `backend-dev` | above | — | **done** |
| Exact metadata-type matching (`model` must not include `model_catalog`) | `backend-dev` | — | H1 | **done** |
| Pass `name_starts_with` prefix in `load_all` | `backend-dev` | — | H1 | deferred — `load_all` is cross-partition (varying `{partition}/` prefix), so no single prefix applies; `load_all_from_partition` already prefixes |
| Fix double-serialization on save; drop redundant `json.loads` | `backend-dev` | migration Q | H4 | deferred — kept tolerant read (`_read_blob_content` handles both encodings); save-side fix needs a data migration for legacy blobs **and** must preserve the `_index_metadata` blob metadata now attached on save (publishing) |

> **Note:** `list_identifiers` / `list_keys` / `build_url` / `check_exists` were landed
> in Phase 1. H2's parallel downloads are a **production-latency** win (no measurable
> effect on Azurite/localhost where per-blob latency is ~1 ms — see results.md).
>
> **Post-rebase (2026-08-20):** main's data-publishing feature independently added a
> parallel blob loader (`_load_blob_names`, for `load_page`); consolidated it onto
> `_read_blob_content` + the shared `HASTE_BLOB_DOWNLOAD_WORKERS` policy so the
> download/deserialize logic (incl. the H4 double-parse tolerance) lives in one place.

**Exit Criteria:**
- [x] New core utilities have 100% statement/branch coverage; cross-backend read
      contracts, response parity, cache, and failure paths are covered.
- [x] Clean 50×5 HTTP fixture returns 50 layers, 250 models/artifacts, and correct
      validation counts with seven logical data-layer calls.

## Phase 3: Queue workers (`hastefuncqueues`) — throughput

**Goal:** Remove the queue-side N+1 and unlock concurrency.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Replace label N+1 in training trigger with `load_filtered` | `backend-dev` | Ph2 H3 | Q2 | not-started |
| Parallelize independent loads (inference, image) with `asyncio.gather` | `backend-dev` | — | Q3 | not-started |
| Add `save_batch`; batch intermediate saves | `backend-dev` | — | Q4 | not-started |
| Load-test `batchSize`>1 / `maxDequeueCount`≥3 / `visibilityTimeout` in `host.json` | `backend-dev` | — | Q1,Q5 | not-started |

**Exit Criteria:**
- [ ] Training/inference triggers issue no full-partition scans.
- [ ] `host.json` changes validated under load without poison-queue regressions.

## Phase 4: UI (`ui/src`) — perceived performance

**Goal:** Stop the poll from thrashing the tree; render only what's needed.

> **Measured (Phase 0):** TTI is API-bound, so backend phases own the TTI win. Rank the
> UI work by impact: **single-flight guard (U7) + poll guard (U1) first** (halve
> effective latency, stop pile-up), then context split (U2); memoization/virtualization
> (U3/U5) and `summary` payload (B6) are lower-value follow-ups.
>
> **Post-rebase (2026-08-20):** main's `PublishedDatasets.jsx` is an in-repo precedent
> for smart polling — 5 s interval that runs *only while active items exist*, with a
> ref to avoid stale closures; consider extracting a shared hook both pages use. Main
> also reworked `AppContext.jsx`/`App.jsx` and many Phase 4 target components, so plan
> U2/U3 against current main, not the original file inventory in findings.md.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Single-flight guard + `AbortController` on `fetchProjectDetails` (dedupe/cancel concurrent calls) | `ui` | — | U7 | **done** |
| Smart poll: send `If-None-Match`, handle `304`, skip `setState` if unchanged | `ui` | Ph1 B7 | U1 | **done** |
| Poll guard: don't fire while a request is in flight | `ui` | — | U1 | **done** |
| Pause polling when hidden and when no active jobs; configurable/adaptive interval | `ui` | — | U1 | **partial** (guards done; interval remains 20 s) |
| Route-level code splitting; load Azure Maps SDK only on map routes | `ui` | — | U6-adjacent | **done** |
| Split volatile fields out of `AppContext` into a lighter provider | `ui` | — | U2 | not-started |
| `React.memo` / `useMemo` / `useCallback` on `LayerRow`/`ModelRow`/`ModelRowMobile` | `ui` | — | U3 | not-started |
| Lazy-render model rows on expand; evaluate list virtualization | `ui` | — | U5 | not-started |
| `Promise.all` the independent GETs in edit/labeling helpers | `ui` | — | U4 | not-started |
| Use `summary` mode for list view; fetch full models on expand | `ui` | Ph1 B6 | B6,U5 | not-started |
| Thumbnail/overview-first in Visualizer; defer full-res second map | `ui` | — | U6 | not-started |

**Exit Criteria:**
- [ ] Project page time-to-interactive < 2s p95 on the synthetic project. Current
      production-bundle observation: **2.12 s**; one initial request, 58 ms render.
- [x] Terminal-job project issued **zero polls** during a 26-second idle window.
- [x] Active-job project issued one non-overlapping conditional poll (`304`).

## Phase 5: Integration & Validation

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| End-to-end run on Docker Compose stack with synthetic large project | `backend-dev` | Ph1–4 | — | not-started |
| Compare against Phase 0 baseline; record deltas | `backend-dev` | above | success-criteria | not-started |
| Update `docs/` (api-overview, architecture) with new params/caching | `backend-dev` | — | — | not-started |

**Exit Criteria:**
- [ ] All success criteria in [README.md](README.md#success-criteria) met and recorded.
- [ ] CI passes (secret-scan, deploy-apps).

## Milestones

| Milestone | Deliverable |
|---|---|
| Baseline captured | Phase 0 numbers in test-plan.md |
| Backend hot path fixed | Seven logical calls, bounded Blob I/O, cache headers |
| Core lib primitives | `load_map` / `load_filtered` / prefix scans merged |
| Queue optimized | N+1 removed, config load-tested |
| UI responsive | smart poll + memoization shipped |
| Validated | End-to-end deltas meet success criteria |

## Agent Summary

| Agent | Phases |
|---|---|
| `backend-dev` | 0, 1, 2, 3, 5 |
| `ui` | 0, 4 |

## Open Questions

- [ ] Ship Phase 1 alone first (backend-only, invisible) to bank the win before UI work?
- [ ] Poll vs push (SignalR) for run-status — defer or fold into Phase 4?
