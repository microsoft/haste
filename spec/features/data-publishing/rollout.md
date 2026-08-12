# Rollout Plan: Data Publishing & Published Datasets

## Rollout Strategy

**Type:** feature-flag (phased)
**Target date:** TBD

Two flags allow shipping Local first and gating Planetary Computer until a
GeoCatalog is provisioned:
- `PUBLISHING_ENABLED` — the whole section + Publish action.
- `PC_PROVIDER_ENABLED` — the Planetary Computer target only.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` (publishing package) | pip install / Docker rebuild | All Function Apps |
| `hastefuncapi` (5 routes) | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `hastefuncqueues` (publish trigger) | GitHub Actions `deploy-apps.yml` | Azure Functions |
| React UI (section + dialog) | GitHub Actions `deploy-apps.yml` | Azure Static Web Apps |
| `publish-queue` | Azurite (local) / Storage (cloud) | Queue Storage |

## Feature Flags

| Flag Name | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| `PUBLISHING_ENABLED` | `hastefuncapi` app setting + UI env (`GetPublishingProviders` gates targets) | off | Enables the Published Datasets section + Publish action | yes |
| `PC_PROVIDER_ENABLED` | `hastefuncapi` app setting | off | Registers/exposes the Planetary Computer provider | yes |

When `PC_PROVIDER_ENABLED=off` or GeoCatalog config is absent, the provider
reports `isConfigured=false` and the UI shows it disabled — a natural kill switch
that never breaks Local publishing.

## Operator Configuration (App Settings)

Provider configuration is **operator-owned**: set at deploy time as Azure
Function App settings (no in-app admin screen). The Bicep threads each setting
from an `azd` environment variable (`azd env set <VAR> <value>`) into the shared
api + queues app settings; credentials are **managed identity only** (nothing
secret is entered or stored by the app).

### Local target

| `azd` env var | App Setting | Default | Purpose |
|---|---|---|---|
| `HASTE_PUBLISHING_ENABLED` | `PUBLISHING_ENABLED` | `false` | Master flag: Published Datasets section + Publish action |
| — | `PUBLISH_QUEUE_NAME` | `publish-queue` | Publish job queue (auto-created at runtime) |

Enabling Local publishing needs only `HASTE_PUBLISHING_ENABLED=true`. The
`publish-queue` and the `publishing-locks` blob container are auto-created on
first use, so no queue/container resources are provisioned. The remaining Local
knobs use code defaults and are only set to override them (directly on the
Function App): `PUBLISH_MAX_TOTAL_BYTES` (5 GiB), `PUBLISHED_DOWNLOAD_SAS_MINUTES`
(15), `PUBLISHING_LOCK_CONTAINER` (`publishing-locks`).

### Planetary Computer target

| `azd` env var | App Setting | Default | Purpose |
|---|---|---|---|
| `HASTE_PC_PROVIDER_ENABLED` | `PC_PROVIDER_ENABLED` | `false` | Register/expose the PC provider |
| `HASTE_PC_GEOCATALOG_URL` | `PC_GEOCATALOG_URL` | (unset) | MPC Pro GeoCatalog base URL (no trailing `/`) |
| `HASTE_PC_EXPLORER_URL` | `PC_EXPLORER_URL` | (unset) | Explorer base URL for published-dataset links |
| `HASTE_PC_INGESTION_SOURCE` | `PC_INGESTION_SOURCE` | (unset) | Ingestion-source name for **private** HASTE containers (`SasToken`); unset for public |
| `HASTE_PC_COLLECTION_PREFIX` | `PC_COLLECTION_PREFIX` | `haste-` | STAC Collection id prefix (one per project/event) |

The STAC `api-version` and the Entra token scope
(`https://geocatalog.spatio.azure.com/.default`) are **code constants**, not
settings. `PC_VERIFY_ATTEMPTS` (ingestion poll bound) uses a code default and is
set directly on the Function App only to override it.

### Operator-owned GeoCatalog side (out-of-band)

The GeoCatalog is provisioned and owned by the operator (external to this
template). Two grants are required and are **not** created by the app deploy:

1. **Function app identity → GeoCatalog data plane** — the api/queues managed
   identity needs a GeoCatalog RBAC role on the GeoCatalog resource so it can
   call the STAC/ingestion APIs. Assigned on the operator's GeoCatalog resource;
   verify the exact role against the target catalog.
2. **GeoCatalog ingestion → HASTE storage** — to ingest published assets the
   GeoCatalog reads them from HASTE blob storage. Either register a `SasToken`
   ingestion source (`HASTE_PC_INGESTION_SOURCE`, no role needed), **or** grant
   the GeoCatalog's managed identity *Storage Blob Data Reader* on the HASTE
   storage account by setting `HASTE_PC_GEOCATALOG_INGEST_PRINCIPAL_ID` to that
   identity's object id (the deploy then makes the assignment; empty = skip).

### Function App host id (required — avoids Singleton-lock failures)

Publishing adds a **timer trigger** (`ReconcilePublishingOperations`, every 5
minutes) to the queues Function App — the app's first timer trigger. Timer
triggers acquire a **host-scoped Singleton lock**, so if the Function App's
auto-generated host id collides with another deployment slot or another app
sharing the same storage account, the timer (and the host) can fail with
*"Unable to acquire Singleton lock"* and *"No script host available"* /
`NoScriptHost` — the app goes unhealthy.

Set a unique **`AzureFunctionsWebHost__hostId`** app setting (≤ 32 chars,
lowercase alphanumeric + hyphens) on **each** Function App **and each deployment
slot** — e.g. `haste-queues-<env>`, `haste-api-<env>`, `haste-titiler-<env>`.
See <https://aka.ms/functions-hostid>. This applies wherever publishing is
enabled (Local *or* PC), since the reconciler timer ships with the Local
feature; it is unrelated to the publishing code itself.

## Rollout Phases

### Phase 1: Dev1 Environment — [date]

- **Target:** SWA `dev1`.
- **Scope:** `PUBLISHING_ENABLED=on`, `PC_PROVIDER_ENABLED=off` (Local only).
- **Duration:** until Local E2E is stable.
- **Deployment:**
  1. Merge PR to `main` (triggers `deploy-apps.yml`).
  2. Seed `publish-queue`; verify in dev1 SWA.
- **Success criteria:**
  - [ ] Publish (Local) → PENDING → PUBLISHED; artifacts downloadable
  - [ ] Section renders all states; queue worker processes messages
  - [ ] Docker Compose stack works
- **Rollback trigger:** publish failures, queue backlog, or section errors.

### Phase 2: Testing Environment — [date]

- **Target:** SWA `testing`; provision a **dev GeoCatalog** + ingestion source.
- **Scope:** enable `PC_PROVIDER_ENABLED=on`. Prereq: a GeoCatalog + user-assigned MI with *Storage Blob Data Reader* on HASTE storage (or a `SasToken` ingestion source for private containers).
- **Duration:** until PC E2E passes.
- **Success criteria:**
  - [ ] PC target ingests collection/items; explorer links resolve
  - [ ] Failure/timeout paths → FAILED with message
  - [ ] Performance thresholds met; no Cosmos/index corruption
- **Rollback trigger:** ingestion auth failures, credential issues, data egress concerns.

### Phase 3: Production — [date]

- **Target:** Production SWA + Function Apps.
- **Federated credentials:** `fed-cred-main.json` (GitHub Actions OIDC); managed
  identity for GeoCatalog + storage.
- **Scope:** `PUBLISHING_ENABLED=on`; `PC_PROVIDER_ENABLED` on only where a
  production GeoCatalog + data-egress approval exist.
- **Success criteria:**
  - [ ] All health checks green; error rate stable
  - [ ] Publisher feedback positive
- **Feature flag cleanup:** remove `PUBLISHING_ENABLED` once GA; keep
  `PC_PROVIDER_ENABLED` as an operational toggle.

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Set `PUBLISHING_ENABLED=off` (and/or `PC_PROVIDER_ENABLED=off`) | ops | immediate |
| 2 | Revert PR / deploy previous commit | `backend-dev` | < 15 min |
| 3 | Verify `PUBLISHED_DATASETS` index doc intact (inert if reverted) | `backend-dev` | |
| 4 | Verify `publish-queue` drained / paused | `backend-dev` | |
| 5 | Verify UI fallback (section hidden, results menu unchanged) | `ui` | |

**Cosmos data rollback required?** no — additive `index` doc is inert when the
feature is off.
**Blob artifacts cleanup needed?** optional — `published/*` copies are inert;
delete if reclaiming storage. **PC collections/items** persist in the GeoCatalog
until deleted via its STAC API (out-of-band, best-effort).

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| Publish success rate | queue worker logs / status transitions | — | < 90% over 1h |
| `publish-queue` depth | Azure Queue Storage metrics | ~0 | > 20 sustained |
| PC ingestion poll duration | provider logs | — | p95 > timeout |
| API error rate (publishing routes) | Azure Functions metrics | — | > 2% |
| `published/` storage growth | Storage metrics | — | unexpected spike |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Publish failures spike | success rate < 90% / 1h | P2 | eng on-call |
| Queue backlog | depth > 20 sustained 15m | P2 | eng on-call |
| PC auth/ingestion failures | repeated FAILED with auth/ingest errors | P2 | eng + ops |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Pre-deploy | Deployment plan + flags |
| Disaster analysts | Release notes | Post-deploy (Local) | "Publish finished datasets from model results" |
| Partners / operators | Docs | At PC GA | Provider config + data-egress guidance |

## Post-Rollout Checklist

- [ ] `PUBLISHING_ENABLED` flag cleaned up (PC flag retained as toggle)
- [ ] Temporary monitoring removed
- [ ] `docs/` updated (publishing feature + provider config)
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`)
- [ ] Docker Compose stack verified with `publish-queue`
- [ ] `CHANGELOG.md` updated
- [ ] Retrospective scheduled
