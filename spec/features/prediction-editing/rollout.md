# Rollout Plan: Prediction Editing

**Contents:** [Rollout Strategy](#rollout-strategy) · [Deployment Targets](#deployment-targets) · [Feature Flags](#feature-flags) · [Rollout Phases](#rollout-phases) · [Rollback Plan](#rollback-plan) · [Monitoring & Alerting](#monitoring--alerting) · [Communication Plan](#communication-plan) · [Post-Rollout Checklist](#post-rollout-checklist)

## Rollout Strategy

**Type:** phased by environment deployment  
**Target date:** TBD

The current implementation does not include API or UI feature flags. Start with
internal dev/test deployments and test projects, then promote to production
after both trained-inference and embedding workflows produce edited versions
without mutating raw outputs. Add feature flags as a follow-up if rollout needs
a runtime kill switch.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` | pip install / Docker rebuild | All Function Apps and queue workers |
| `hastefuncapi` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `hastefuncqueues` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| React UI | GitHub Actions `deploy-apps.yml` | Azure Static Web Apps |

## Feature Flags

| Flag Name | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| — | — | — | No prediction-editing feature flags are implemented in the current branch. | no |

## Rollout Phases

### Phase 1: Dev1 Environment — TBD

- **Target:** SWA `dev1` environment
- **Duration:** one sprint or until both workflows pass E2E validation
- **Deployment:**
  1. Deploy the branch to dev1.
  2. Verify trained-inference and embedding edit flows against test projects.
- **Success criteria:**
  - [ ] `GetPredictionEditSession` reports correct readiness for both workflows without enqueueing.
  - [ ] `PutPreparePredictionTilesQueueMessage` queues missing PMTiles and sidecars.
  - [ ] Queue workers generate missing PMTiles and sidecars.
  - [ ] UI renders the editor, class filters, selection, and threshold behavior.
  - [ ] Saving creates `edit_v1` without changing raw `Model.gpkgUrl`.
- **Rollback trigger:** Any raw artifact mutation, repeated prep queue failures,
  or browser crashes on representative layers.

### Phase 2: Testing Environment — TBD

- **Target:** SWA `testing` environment
- **Duration:** one response exercise or agreed analyst validation window
- **Success criteria:**
  - [ ] Analysts can complete and download edited versions for trained models.
  - [ ] Analysts can complete and download edited versions for embedding models.
  - [ ] The documented editor/report threshold default split is accepted by testers.
  - [ ] Memory and duration metrics stay within accepted bounds.
  - [ ] No regression from baseline UI lint behavior.
- **Rollback trigger:** Save failures above the agreed threshold, invalid row-order
  output, or editor performance that blocks analyst use.

### Phase 3: Production — TBD

- **Target:** Production SWA + Function Apps
- **Federated credentials:** `fed-cred-main.json` (GitHub Actions OIDC)
- **Success criteria:**
  - [ ] Error rate and queue depth remain stable after production deployment.
  - [ ] First production edited version downloads and validates row count/order.
  - [ ] Analyst feedback confirms the editor is usable in dark and light themes.
- **Kill-switch follow-up:** If production requires runtime disablement, add the
  missing API/UI feature flags before broad enablement.

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Redeploy the previous UI build to remove Edit entry points | `ui` | <1 hour |
| 2 | Redeploy the previous API build if direct prediction-editing calls must fail closed | `backend-dev` | <1 hour |
| 3 | Stop or drain `prediction-edit-prep-queue` if workers are failing | `backend-dev` | <30 min |
| 4 | Verify raw `Model.gpkgUrl` and existing reports still work | `backend-validation` | <1 hour |

**Cosmos data rollback required?** no — new fields are optional and backward-compatible.  
**Blob artifacts cleanup needed?** no for functional rollback — edited GeoPackages,
PMTiles, and sidecars are additive derived artifacts. Cleanup can run later if
storage cost requires it.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| Prediction edit session error rate | Azure Functions metrics / Application Insights | new metric | >5% 5xx over 15 minutes |
| `PutEditedPredictions` duration and memory | Application Insights | new metric | p95 near function timeout or memory ceiling |
| Prep queue depth | Azure Queue Storage metrics | 0 when idle | sustained growth for 30 minutes |
| Prep job failures | queue worker logs / Batch task status | 0 | any repeated failure for same model |
| Edited artifact upload failures | Blob SDK logs | 0 | any production failure |
| Browser-side editor errors | UI telemetry / support reports | 0 | repeated sidecar parse or map-load failures |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Prep queue stalled | `prediction-edit-prep-queue` depth rising and no completions for 30 minutes | P2 | Engineering on-call |
| Save failures | `PutEditedPredictions` 5xx rate >5% over 15 minutes | P2 | Engineering on-call |
| Row-order validation failure | Any 422 row-count/order failure in production | P1 | Backend + GIS leads |
| Blob upload failures | Edited GeoPackage upload errors >0 for production saves | P2 | Engineering on-call |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Before dev1 deployment | Prediction editing has no runtime flags in this branch; verify both workflows and artifact immutability before promotion. |
| Disaster analysts | Release notes / Teams | Before testing enablement | Edit completed predictions, save numbered versions, and download them; reports still use raw outputs. |
| Partners | Release notes | At production enablement | Edited prediction GeoPackages may be shared as downloadable derived files; downstream reports are unchanged. |

## Post-Rollout Checklist

- [ ] Decide whether to add runtime feature flags before broad production use.
- [ ] Temporary rollout monitoring removed or converted to normal dashboards.
- [ ] End-user docs updated with edit workflow and out-of-scope downstream behavior.
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`) if public docs changed.
- [ ] Docker Compose stack verified after release.
- [ ] `CHANGELOG.md` updated.
- [ ] Follow-up spec opened for downstream consumption of edited versions.
