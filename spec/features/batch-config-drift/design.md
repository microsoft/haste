# Design — Batch configuration drift

## 1. Setting resolution (`config.py`)

`registry_server` is resolved through a helper rather than a bare `os.getenv`:

```
AZURE_BATCH_REGISTRY_SERVER              -> used as-is (scheme stripped)
  else AZURE_BATCH_REGISTRY_SERVER_URL   -> used + deprecation warning logged
  else "<registry-name>.azurecr.io"      -> placeholder, caught by validation
```

Normalization strips any `http(s)://` prefix and trailing `/`, because Azure
Batch's `ContainerRegistry.registry_server` expects a bare login server
(`myacr.azurecr.io`) while the legacy setting stored a URL.

Dual-reading — rather than a clean break — keeps partner environments working
across the upgrade: they hold only the old setting until an operator renames it.

## 2. Fail-fast validation (`utils/batch_config.py`)

`validate_batch_config(batch_config, manage_pools=None)` raises
`BatchConfigurationError` listing every required setting that is empty or still
contains a `<placeholder>`, mapped back to the application setting name an
operator would set.

Two tiers, because the requirement is conditional:

| Tier | Settings | When required |
|---|---|---|
| Always | `AZURE_BATCH_ACCOUNT_NAME`, `AZURE_BATCH_URL`, `AZURE_BATCH_OUTPUT_CONTAINER_URL` | every submission |
| Pool management | `AZURE_BATCH_REGISTRY_SERVER`, `AZURE_BATCH_REGISTRY_IMAGE`, `AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID` | only when `AZURE_BATCH_MANAGE_POOLS` is true |

Environments on pre-created autoscale pools never read the registry settings, so
requiring them unconditionally would break working deployments.

**Call site.** Validation runs at the start of `AzureBatchRunner.add_task`, not
`__init__`. The runner is constructed eagerly by every `ImageryProcessor`,
including on read-only status endpoints; validating in the constructor would
fail unrelated requests. `add_task` is the actual submission boundary, and the
queue trigger's exception handler writes the message to the image layer's
`statusMessage`, so the operator sees the missing setting in the UI.

## 3. Job/pool rebinding (`runners/azure_batch.py`)

Batch job ids default to the configured pool id, so a job outlives the pool
whose name it borrowed. `create_job` previously did:

```
job exists -> enable it            # keeps the ORIGINAL pool binding
job absent -> create bound to pool
```

That silently defeats capacity-aware routing (the job stays on whichever pool
created it, ignoring `select_pool`) and hard-fails once the original pool is
renamed or deleted — tasks queue into a job bound to a pool that no longer
exists. `_rebind_job_pool` now patches `pool_info` when the existing binding
differs from the selected pool, and falls back to a pool-scoped job id when
Batch refuses (which it does whenever the job still has active tasks).

> Superseded by [`../batch-pool-job-binding/`](../batch-pool-job-binding/):
> rebinding cannot work while a job is running, so job ids are now scoped to
> the selected pool instead.

## 4. Deploy-path parity

`deploy_apps.sh` gains the missing settings. Pool wiring is overridable per
environment via GitHub Environment variables, with defaults that reproduce the
previous single-pool behavior:

| Script variable | Application setting | Default |
|---|---|---|
| `BATCH_TRAINING_POOL_ID` | `AZURE_BATCH_TRAINING_POOL_ID` | derived `<prefix>-haste-<suffix>-pool` |
| `BATCH_IMAGERYPREP_POOL_ID` | `AZURE_BATCH_IMAGERYPREP_POOL_ID` | derived |
| `BATCH_TRAINING_POOL_IDS` | `AZURE_BATCH_TRAINING_POOL_IDS` | empty |
| `BATCH_INFERENCE_POOL_IDS` | `AZURE_BATCH_INFERENCE_POOL_IDS` | empty |
| `BATCH_IMAGERYPREP_POOL_IDS` | `AZURE_BATCH_IMAGERYPREP_POOL_IDS` | empty |
| `BATCH_USE_SAS` | `AZURE_BATCH_USE_SAS` | `false` |
| `BATCH_MANAGE_POOLS` | `AZURE_BATCH_MANAGE_POOLS` | `true` |

The derived pool name is retained as the default only for backward
compatibility; environments on shared pools must set the overrides, because the
singular id also names the Batch job.

## 5. CI guard (`check_env_drift.py`)

Parses the code with `ast` (not regex) to find every `os.getenv` /
`os.environ.get` / `os.environ[...]` read, classifying a variable as **required**
when it has no default or its default still contains a `<placeholder>`. It then
compares that set against the settings emitted by `deploy_apps.sh` (scoped to
the `appsettings set` block, so resource tags are not misread as settings) and
`functions.bicep`, and fails when a required variable is missing from either.

It also reports the inverse — settings emitted by a deploy path that no code
reads — which is the specific signature of a half-applied rename, and is what
made `AZURE_BATCH_REGISTRY_SERVER_URL` detectable.

Genuinely optional variables (alternative storage backends, the local Docker
runner, container-side GDAL tuning, platform-provided values, and the
deliberately unemitted legacy fallback) are exempt via a documented `ALLOWLIST`.
