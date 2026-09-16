# Execution Plan: Image Layer & Model Run Loading Performance

Sequenced by impact-per-risk. Phase 0 establishes a baseline so every later phase is
measured, not guessed. Backend before UI: the backend N+1 is the dominant cost and its
fixes are transparent to the UI. Each phase is independently shippable.

## Phase 0: Baseline & Instrumentation — DONE (2026-08-03)

**Goal:** Make the problem measurable before changing it.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Add opt-in round-trip counter + timing (`hastelib/.../utils/perf.py`, wired into `MetadataProcessor` reads + `GetProjectDetails` via `HASTE_PERF`) | `backend-dev` | — | B1–B4 | **done** |
| Seed script for synthetic L×M project (`tools/seed_synthetic_project.py`) | `backend-dev` | — | cost-model | **done** |
| Capture baseline round-trips + payload (`tools/phase0_baseline.py` → `results.md`) | `backend-dev` | above | success-criteria | **done** |
| HTTP latency harness for running stack (`tools/bench_api_http.py`) | `backend-dev` | above | success-criteria | **done** |
| Capture real API p50/p95 latency against running stack (Docker + Azurite) | `backend-dev` | stack up + seed | success-criteria | **done** |
| Compose overlay + reproducible run (`docker/docker-compose.perf.yml`) | `backend-dev` | — | — | **done** |
| Record UI time-to-interactive + poll cost (Playwright, `tools/ui_bench.cjs`) | `ui` | stack up | U1 | **done** |

**Exit Criteria:**
- [x] Baseline round-trips (33 / 243 / **603**) + payload captured in
      [results.md](results.md) and `test-plan.md`; per-op breakdown quantifies B1/B2.
- [x] Real API latency captured (large **20.8 s p50 / 21.8 s p95** on Azurite;
      storage = 13.4 s of that). Confirms the reported symptom.
- [x] Browser-side UI TTI captured (large **40.3 s**; API-bound + fired twice
      concurrently; 20 s poll re-does the full call). Phase 0 complete.

## Phase 1: Backend API hot path (`hastefuncapi`) — highest ROI

**Goal:** Collapse `GetProjectDetails` to a constant number of storage reads. No API
contract change; UI untouched.

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Hoist `LABELS.load_all_from_partition` out of the layer loop (load once) | `backend-dev` | P0 | B1 | not-started |
| Parallelize top-level reads (project/layers/models/labels) with `asyncio.gather` | `backend-dev` | P0 | B4 | not-started |
| Batch per-model artifacts + `labelsUrl` via `load_map` (bounded parallel) | `backend-dev` | Ph2 `load_map` | B2 | not-started |
| Batch per-layer VALIDATION via `load_map` | `backend-dev` | Ph2 `load_map` | B3 | not-started |
| Apply the same hoist to `GenerateProjectStats` | `backend-dev` | B1 | B5 | not-started |
| Add `ETag` + `Cache-Control` + `304` handling to `GetProjectDetails` | `backend-dev` | — | B7 | not-started |
| Add optional `summary` / `includeArtifacts=false` response modes | `backend-dev` | above | B6 | not-started |

**Exit Criteria:**
- [ ] Round-trip count for 50×5 project drops from ~600 to ≤ ~6 + 2 bounded fan-outs.
- [ ] `GetProjectDetails` p95 < 1.5s on the synthetic project.
- [ ] Existing UI still works unchanged (contract preserved).

## Phase 2: Core library (`hastelib`) — enables Phase 1 batch/filter

**Goal:** Give the API layer the primitives it needs and remove data-layer waste.
(Ships alongside Phase 1; `load_map` is a prerequisite for B2/B3.)

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Add `MetadataProcessor.load_map(keys, max_workers)` (bounded `ThreadPoolExecutor`) | `backend-dev` | — | H2 | not-started |
| Add `MetadataProcessor.load_filtered(predicate)` | `backend-dev` | — | H3 | not-started |
| Pass `name_starts_with` prefix in `load_all`; add metadata-only listing | `backend-dev` | — | H1 | not-started |
| Parallelize download loops in `load_all*` and `fetch_artifact` | `backend-dev` | — | H2 | not-started |
| Fix double-serialization on save; drop redundant `json.loads` | `backend-dev` | migration Q | H4 | not-started |
| Reuse module-level `BlobServiceClient` (keyed by conn-string) | `backend-dev` | — | H5 | not-started |
| Unit tests in `hastelib/tests/` for new methods + parity of old behavior | `backend-dev` | all above | — | not-started |

**Exit Criteria:**
- [ ] `hastelib` unit tests pass; `load_filtered`/`load_map` covered.
- [ ] No container-wide scans without a prefix remain in `load_all`.

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

| Task | Agent | Dependencies | Ref | Status |
|---|---|---|---|---|
| Single-flight guard + `AbortController` on `fetchProjectDetails` (dedupe/cancel concurrent calls) | `ui` | — | U7 | not-started |
| Smart poll: send `If-None-Match`, handle `304`, skip `setState` if unchanged | `ui` | Ph1 B7 | U1 | not-started |
| Poll guard: don't fire while a request is in flight (response can exceed 20 s interval) | `ui` | — | U1 | not-started |
| Pause polling when tab hidden; make interval configurable/adaptive | `ui` | — | U1 | not-started |
| Split volatile fields out of `AppContext` into a lighter provider | `ui` | — | U2 | not-started |
| `React.memo` / `useMemo` / `useCallback` on `LayerRow`/`ModelRow`/`ModelRowMobile` | `ui` | — | U3 | not-started |
| Lazy-render model rows on expand; evaluate list virtualization | `ui` | — | U5 | not-started |
| `Promise.all` the independent GETs in edit/labeling helpers | `ui` | — | U4 | not-started |
| Use `summary` mode for list view; fetch full models on expand | `ui` | Ph1 B6 | B6,U5 | not-started |
| Thumbnail/overview-first in Visualizer; defer full-res second map | `ui` | — | U6 | not-started |

**Exit Criteria:**
- [ ] Project page time-to-interactive < 2s p95 on the synthetic project.
- [ ] Idle open-project CPU/network drops measurably (no full refetch/re-render per poll).

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
| Backend hot path fixed | `GetProjectDetails` O(1) reads, cache headers |
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
