# Impact Analysis: Image Layer & Model Run Loading Performance

## Contents

- [Scope](#scope-of-change)
- [Azure Services](#azure-service-impact)
- [Dependencies](#dependency-analysis)
- [Risks](#risk-assessment)
- [Performance](#performance-impact-measured-baseline--target)
- [Security](#security-impact)
- [Rollback](#rollback-assessment)

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
| Blob Storage / Cosmos | Fewer repeated scans and overlapped keyed reads | Lower transaction count than baseline, but still proportional to returned Blob records |
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
| Concurrent fan-out exhausts Functions threads | low after mitigation | med | One process-wide executor caps blocking I/O at `HASTE_BLOB_DOWNLOAD_WORKERS`; UI/API single-flight removes duplicate same-key work. Multi-request load testing remains required. |
| `batchSize`>1 changes ordering/poison behavior | med | med | Gate behind load test; keep separate from Phase 1; revert via config |
| Cache headers serve stale run-status to UI | low | med | Short `max-age` (≤15s); UI still change-detects; runs move to terminal states, not backwards |
| UI context split / memo introduces render regressions | med | low | Ship incrementally; visual + interaction QA per component |

## Performance Impact (measured baseline → target)

Phase 0 baselines (50×5, Azurite/dev — lower bound; see [results.md](results.md)):

- **API latency:** `GetProjectDetails` **20.8 s p50 / 21.8 s p95** baseline;
  hardened clean fixture **1.85 s / 2.00 s uncached** and **9.1 / 12.2 ms cached**.
- **Logical data-layer calls:** **603 → 7**. This is not an Azure transaction count.
- **UI time-to-interactive:** **40.3 s** (large) → target **< 2 s**. TTI is API-bound
  (~2 s render over the API call), so the backend fix drives most of this; the UI
  single-flight/poll guards remove the ~2× amplification and request pile-up.
- **Backend load:** idle projects no longer poll; active-job polls do not overlap.
  Fresh cache hits use zero data-layer calls. Active polls after cache expiry still read
  storage because no materialized project version exists.
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
