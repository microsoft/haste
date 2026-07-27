# Batch configuration drift

**Status:** in-progress
**Type:** modification (fix)
**Related:** [`../batch-compute-expansion/`](../batch-compute-expansion/) — the
change whose deploy-path wiring was incomplete.

## Problem

Image-layer creation failed in a deployment environment before any task reached
Azure Batch:

```
Code: InvalidPropertyValue
PropertyName:  registryServer
PropertyValue: <registry-name>.azurecr.io
Reason: The specified registry is an invalid docker registry server name
```

`<registry-name>.azurecr.io` is `hastegeo`'s placeholder default, so the real
setting never reached the running app.

## Root causes

| # | Cause |
|---|---|
| RC1 | `Config` reads `AZURE_BATCH_REGISTRY_SERVER`; `deploy_apps.sh`, `functions.bicep` and `local.settings.example.jsonc` all emitted `AZURE_BATCH_REGISTRY_SERVER_URL`, which no code read. |
| RC2 | `deploy_apps.sh` never emitted the shared-pool settings introduced with the multi-tenant pools (`AZURE_BATCH_*_POOL_IDS`, `AZURE_BATCH_USE_SAS`, `AZURE_BATCH_MANAGE_POOLS`), so environments deployed through it ran the legacy single-pool path against renamed pools. |
| RC3 | Placeholder defaults turned a missing setting into an opaque Azure error raised deep inside pool creation. |
| RC4 | Nothing compared the variables the code reads against the variables the deploy paths emit, so the drift was invisible until an environment broke. |
| RC5 | `create_job` re-enabled an existing job without re-pointing it, leaving jobs pinned to the pool that first created them — and permanently broken once that pool was deleted. |
| RC6 | `EMBEDDING_QUEUE_NAME` was emitted by neither Azure deploy path. |

## Scope

- `hastelib/src/hastegeo/core/config.py` — dual-read + normalize the registry
  server setting.
- `hastelib/src/hastegeo/core/utils/batch_config.py` *(new)* — fail-fast
  validation naming the missing application setting.
- `hastelib/src/hastegeo/core/runners/azure_batch.py` — validate before
  submitting, rebind stale job/pool bindings, whitelist both container images.
- `.github/scripts/deploy_apps.sh` + `.github/workflows/deploy-apps.yml` —
  emit the full setting set, with per-environment pool overrides.
- `infra/modules/functions.bicep` (+ regenerated `infra/main.json`).
- `.github/scripts/check_env_drift.py` + `.github/workflows/config-drift.yml`
  *(new)* — CI guard.
- `local.settings.example.jsonc`, `docs/configuration.md`,
  `docs/api/hastefuncqueues.md`, `api/hastefuncqueues/README.md`, `CHANGELOG.md`.

## Non-goals

- Consolidating the two divergent deploy paths (`deploy_apps.sh` vs
  `infra/main.bicep`). Tracked in
  [`../infra-iac-migration/`](../infra-iac-migration/).
- Migrating `azure-batch` to the 15.x track-2 SDK.

## Agent assignment

| Area | Implements | Validates |
|---|---|---|
| `hastelib/`, `.github/`, `infra/` | `backend-dev` | `backend-validation` |
| Docs + spec | `backend-dev` | `orchestrator` |

## Acceptance criteria

1. `AZURE_BATCH_REGISTRY_SERVER` resolves from the canonical name, falls back to
   the legacy `_URL` name, and strips any scheme.
2. Submitting with an unresolved placeholder raises an error naming the
   application setting, before any Batch API call.
3. Both deploy paths emit every required setting.
4. `check_env_drift.py` exits non-zero on the pre-fix tree and zero after.
5. A job bound to a stale pool is rebound to the selected pool.
