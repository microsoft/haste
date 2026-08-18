# Impact Analysis: Batch node-loss resilience

## Scope of change

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library — runners | `hastelib/src/hastegeo/core/runners/azure_batch.py` | modified | medium |
| Core library — runners | `hastelib/src/hastegeo/core/runners/local.py` | modified | low |
| Core library — processors | `hastelib/src/hastegeo/core/processors/imagery.py` | modified | medium |
| Core library — utils | `hastelib/src/hastegeo/core/utils/errors.py` | new | low |
| Core library — utils | `hastelib/src/hastegeo/core/utils/blob.py` | modified (additive) | low |
| Queue workers | `api/hastefuncqueues/function_app.py` | modified | low |
| Docs | `docs/api/hastefuncqueues.md`, `api/hastefuncqueues/README.md` | modified | low |

No infrastructure, Bicep, UI, CI or dependency changes.

## Azure service impact

| Service | Change | Cost Impact |
|---|---|---|
| Azure Batch | None to pool or account configuration. Tasks now register one extra `OutputFile` pattern (`logs/*.*`). | negligible |
| Blob Storage | Imagery tasks additionally upload `logs/imagery_friendly.log` (a few KB per layer). One extra GET per layer on the fallback path. | negligible |
| Azure Functions | Node-file reads may now retry up to 5 times with 4–10s backoff (worst case ~40s added per failing read). `functionTimeout` is `23:59:59`, so no timeout risk. | negligible |

## Dependency analysis

### Upstream

| Dependency | Type | Status | Risk if unavailable |
|---|---|---|---|
| `azure-batch==14.2.0` error model (`.error.code`) | library | pinned, available | Classification degrades to "not retryable" — i.e. today's behavior |
| `tenacity` | library | already a dependency | none |
| `requests` | library | already a dependency | fallback returns `None`; manifest miss fails the layer as before |
| Batch `OutputFile` upload on task completion | platform | in use since before this change | fallback finds nothing; behaves as today |

### Downstream

| Consumer | How affected | Breaking? | Migration needed? |
|---|---|---|---|
| `ImageryPostProcessor` | gains a blob fallback | no | no |
| `train` / `inference` / `artifacts` / `embedding` processors | inherit the runner-level retry and tolerant cleanup; `get_filecontent_from_task` can now return `None` where it previously raised | no — all callers already branch on falsy content | no |
| `LocalRunner` | `file_pattern` may be a list | no — string callers unchanged | no |
| Existing Cosmos/Blob documents | none — no schema change | no | no |
| Already-failed dev1 layers | not repaired retroactively | no | re-run the layer |

## Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A returned `None` masks a real failure in a non-imagery workload | low | medium | Only node-unavailability is converted; every other Batch error still propagates. Covered by `test_propagates_unrelated_batch_errors`. |
| Retrying widens the window in which a genuinely broken node stalls a message | low | low | Budget unchanged (5 attempts / 4–10s); `NodeNotFound` is not retried at all |
| Blob fallback reads a stale manifest from a previous task | very low | medium | The path is scoped by `taskId`, which is unique per submission |
| `logs/*.*` upload leaks unintended files | very low | low | The imageryprep container writes only `imagery_friendly.log` there |
| Fallback failure hides the original error | low | medium | `fetch_url_text` and the fallback block never raise; both log and return `None` |
| A layer completes on the blob copy while the node copy was more recent | very low | low | Batch uploads on task completion, so the blob copy is the final state |

## Performance impact

- **Happy path:** unchanged — the node copy is still read first, and the fallback only runs when that returns nothing.
- **Failure path:** up to ~40s of backoff per unreadable file before falling back, replacing an immediate permanent failure.
- **Batch compute:** unchanged. No pool, node-count or VM SKU changes.

## Security impact

- [ ] New API endpoints exposed? — **no**
- [ ] New data classification handled? — **no**
- [ ] MSAL/Entra ID auth changes? — **no**
- [ ] New secrets or connection strings? — **no**. The fallback reuses the SAS URL the data layer already issues (`get_file_remote_path`), the same one handed to the UI.
- [ ] CORS changes? — **no**
- [ ] New dependencies? — **no**

`describe_exception` strips the service `RequestId`/`Time` trailer from
user-facing status text; the full exception is still written to the function
logs via `traceback.format_exc()`.

## Compliance & data impact

- No change to data residency, retention or partner sharing.
- One additional small log file per imagery layer in the existing outputs
  container, under the existing retention policy.
- No new Python or npm dependencies, so no Component Governance implications.

## Rollback assessment

- **Reversibility:** fully reversible — code-only, no state or schema migration.
- **Cosmos data:** unaffected.
- **Blob data:** the extra `imagery_friendly.log` blobs are harmless if the
  change is reverted; nothing reads them unless the fallback exists.
- **API:** no contract change.
- **Estimated rollback time:** one revert + redeploy (<15 min).
