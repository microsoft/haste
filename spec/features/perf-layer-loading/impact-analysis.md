# Impact Analysis: Image Layer & Model Run Loading Performance

## Scope of Change

| Component | Path | Type | Severity |
|---|---|---|---|
| REST API | `api/hastefuncapi/function_app.py` | modified (`GetProjectDetails`, `GenerateProjectStats`) | high |
| Core library | `hastelib/src/hastegeo/core/processors/metadata.py` | modified (new methods) | medium |
| Core library | `hastelib/src/hastegeo/core/data_layer/azure_blob_storage_data_layer.py` | modified | medium |
| Core library | `hastelib/src/hastegeo/core/artifact_storage/azure_blob_artifact_storage.py` | modified | low |
| Core library | `hastelib/src/hastegeo/core/blob.py` | modified (client reuse) | low |
| Queue workers | `api/hastefuncqueues/function_app.py` + `host.json` | modified | medium |
| React UI | `ui/src/Components/Project.jsx`, `AppContext.jsx`, `ProjectManagement/*` | modified | medium |

## Azure Service Impact

| Service | Change | Cost Impact |
|---|---|---|
| Blob Storage / Cosmos | Far fewer read round-trips per `GetProjectDetails`; prefix-scoped listings | **Lower** transaction count & egress (especially with 20s poll × N clients) |
| Azure Functions | Lower per-request CPU/wall-time; `gather` uses more threads briefly per request | Net **lower** consumption; watch thread-pool sizing under load |
| Queue Storage | `batchSize`>1 raises concurrency per instance | Neutral–lower; validate scale behavior |

## Dependency Analysis

### Upstream (needed by this work)
| Dependency | Status | Risk |
|---|---|---|
| `UnifiedDataLayer` predicate support | to confirm | If Blob path can't filter server-side, `load_filtered` = prefix scan + in-layer filter (still removes caller N+1, smaller win) |
| Existing blob serialization format | available | H4 fix depends on whether legacy blobs are double-encoded |

### Downstream (affected)
| Consumer | How | Breaking? | Migration? |
|---|---|---|---|
| UI `GetProjectDetails` callers | Same default shape; new optional params | no | no |
| UI polling | Gains `304` fast-path; old client still works | no | no |
| Existing blobs (if double-encoded) | H4 read-path change | **maybe** | Add back-compat read (accept single- or double-encoded) before removing re-parse |
| Queue message format | unchanged | no | no |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| H4 double-serialize fix breaks reads of legacy blobs | med | high | Keep tolerant read (try single, fall back to double) during transition; migrate lazily on next save |
| `asyncio.gather` + `ThreadPoolExecutor` fan-out exhausts Functions thread pool under concurrency | med → **confirmed relevant** | med | **Phase 0 evidence:** two *concurrent* `GetProjectDetails` calls already ~2× the latency (38 s vs 21 s) — the worker contends today. Bound workers via `HASTE_METADATA_LOAD_WORKERS`, cap total in-flight, and fix the UI single-flight (U7) so fewer concurrent requests hit the API; load-test the fan-out under ≥2 concurrent requests |
| `batchSize`>1 changes ordering/poison behavior | med | med | Gate behind load test; keep separate from Phase 1; revert via config |
| Cache headers serve stale run-status to UI | low | med | Short `max-age` (≤15s); UI still change-detects; runs move to terminal states, not backwards |
| UI context split / memo introduces render regressions | med | low | Ship incrementally; visual + interaction QA per component |

## Performance Impact (measured baseline → target)

Phase 0 baselines (50×5, Azurite/dev — lower bound; see [results.md](results.md)):

- **API latency:** `GetProjectDetails` **20.8 s p50 / 21.8 s p95** → target **< 1.5 s**;
  round-trips **603 → ≤ ~6 + 2 bounded fan-outs**.
- **UI time-to-interactive:** **40.3 s** (large) → target **< 2 s**. TTI is API-bound
  (~2 s render over the API call), so the backend fix drives most of this; the UI
  single-flight/poll guards remove the ~2× amplification and request pile-up.
- **Backend load:** the 20 s poll currently re-issues the full 603-round-trip call
  (measured 36.5 s per poll) — worse, response > interval so polls overlap. Fixing the
  poll guard + `304` collapses idle per-open-project storage transactions dramatically.
- **Queue throughput:** higher with `batchSize`>1; training/inference lose partition scans.

## Security Impact

- [x] No new endpoints exposed; `GetProjectDetails` auth level unchanged.
- [x] No new data classification; same imagery/metadata.
- [x] No auth/CORS changes.
- [ ] `ETag` is a payload hash — ensure it doesn't leak across tenants (it's per-project,
      auth already scopes access). Confirm no cross-user cache reuse.

## Rollback Assessment

- **Reversibility:** fully reversible — behavioral/perf changes, no schema migration
  required (H4 handled with a tolerant read path, so no data rewrite).
- **API:** contract preserved; new params are opt-in. Revert = redeploy prior build.
- **Config:** `host.json` / env knobs revert independently.
- **Estimated rollback time:** one redeploy (minutes).
