# Rollout Plan: Prediction Editing

**Contents:** [Rollout Strategy](#rollout-strategy) · [Deployment Targets](#deployment-targets) · [Feature Flags](#feature-flags) · [Rollout Phases](#rollout-phases) · [Rollback Plan](#rollback-plan) · [Monitoring & Alerting](#monitoring--alerting) · [Communication Plan](#communication-plan) · [Post-Rollout Checklist](#post-rollout-checklist)

## Rollout Strategy

**Type:** phased by environment deployment  
**Target date:** TBD

The current implementation does not include API or UI feature flags. Start with
internal dev/test deployments and test projects, then promote to production
after both trained-inference and embedding workflows can open View Results,
render vector footprints, enter Visualizer edit mode, save edited versions, and
read the expected version from visualizer, validation, and assessment readers.
Add feature flags as a follow-up if rollout needs a runtime kill switch.

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
  2. Verify trained-inference and embedding View Results flows against test
     projects.
  3. Verify edit mode is entered from the existing `/visualizer/...` route by
     the pencil affordance and `E` shortcut, not a standalone editor route
     (`ui/src/Components/AppBody.jsx:73-75`,
     `ui/src/Components/Visualizer/Labels.jsx:117-128`).
- **Success criteria:**
  - [ ] Server-derived `predictionsReady` enables Results consistently for
        trained and embedding models.
  - [ ] `GetVisualizerResults` returns the vector-first payload documented for
        PMTiles, prediction attributes, readiness, version metadata, flavor,
        and nullable classic rasters (`docs/api/hastefuncapi.md:78-157`).
  - [ ] `PutPreparePredictionTilesQueueMessage` queues missing PMTiles and
        sidecars only when needed.
  - [ ] Queue workers generate missing PMTiles and sidecars.
  - [ ] UI renders vectors, filters, selection, threshold behavior when
        supported, and edit-mode entry/exit.
  - [ ] Saving creates `edit_v1` without changing raw `Model.gpkgUrl`.
  - [ ] Validation and assessment endpoints accept `version`; default behavior
        selects the newest edited version while `version=0` selects raw.
- **Rollback trigger:** Any raw artifact mutation, repeated prep queue failures,
  failed Visualizer payload contract, report reader regression, or browser
  crashes on representative layers.

### Phase 2: Testing Environment — TBD

- **Target:** SWA `testing` environment
- **Duration:** one response exercise or agreed analyst validation window
- **Success criteria:**
  - [ ] Analysts can open View Results and save edited versions for trained
        models.
  - [ ] Analysts can open View Results and save edited versions for embedding
        models.
  - [ ] Analysts understand that version history is read-only in the UI: the
        payload reports which version is mapped, but selecting another version
        does not refetch in this branch.
  - [ ] The documented split is accepted: validation metrics read edited
        `damaged`, while assessment counts still threshold the producer's
        preserved `damage_pct_0m`.
  - [ ] Memory and duration metrics stay within accepted bounds.
  - [ ] No regression from baseline UI lint behavior.
- **Rollback trigger:** Save failures above the agreed threshold, invalid
  row-order output, confusing report semantics that block analyst use, or editor
  performance that blocks analyst workflows.

### Phase 3: Production — TBD

- **Target:** Production SWA + Function Apps
- **Federated credentials:** `fed-cred-main.json` (GitHub Actions OIDC)
- **Success criteria:**
  - [ ] Error rate and queue depth remain stable after production deployment.
  - [ ] First production trained and embedding View Results sessions render
        vector footprints.
  - [ ] First production edited version downloads and validates row count/order.
  - [ ] Validation report default/`version=0` behavior is verified on the first
        edited production model.
  - [ ] Assessment report asymmetry is visible in release notes and support
        guidance.
  - [ ] Analyst feedback confirms the editor is usable in dark and light themes.
- **Kill-switch follow-up:** If production requires runtime disablement, add the
  missing API/UI feature flags before broad enablement.

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Redeploy the previous UI build to remove Visualizer edit-mode affordances and embedding View Results entry points | `ui` | <1 hour |
| 2 | Redeploy the previous API build if vector-first visualizer or prediction-editing calls must fail closed | `backend-dev` | <1 hour |
| 3 | Stop or drain `prediction-edit-prep-queue` if workers are failing | `backend-dev` | <30 min |
| 4 | Verify raw `Model.gpkgUrl`, classic raster results, and existing reports still work | `backend-validation` | <1 hour |
| 5 | Tell analysts that edited versions saved before rollback remain derived artifacts but may not be selected by the reverted UI/API | `orchestrator` | <1 hour |

**Cosmos data rollback required?** no — new fields are optional and backward-compatible.  
**Blob artifacts cleanup needed?** no for functional rollback — edited GeoPackages,
PMTiles, and sidecars are additive derived artifacts. Cleanup can run later if
storage cost requires it.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| `GetVisualizerResults` error rate | Azure Functions metrics / Application Insights | existing route with new payload | >5% 5xx over 15 minutes |
| Prediction edit session error rate | Azure Functions metrics / Application Insights | new metric | >5% 5xx over 15 minutes |
| `PutEditedPredictions` duration and memory | Application Insights | new metric | p95 near function timeout or memory ceiling |
| Prep queue depth | Azure Queue Storage metrics | 0 when idle | sustained growth for 30 minutes |
| Prep job failures | queue worker logs / Batch task status | 0 | any repeated failure for same model or layer |
| Edited artifact upload failures | Blob SDK logs | 0 | any production failure |
| Validation/assessment report failures with `version` | Application Insights | new metric | repeated 4xx/5xx for valid version requests |
| Browser-side Visualizer errors | UI telemetry / support reports | 0 | repeated sidecar parse, PMTiles, or map-load failures |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Visualizer failures | `GetVisualizerResults` 5xx rate >5% over 15 minutes | P2 | Engineering on-call |
| Prep queue stalled | `prediction-edit-prep-queue` depth rising and no completions for 30 minutes | P2 | Engineering on-call |
| Save failures | `PutEditedPredictions` 5xx rate >5% over 15 minutes | P2 | Engineering on-call |
| Row-order validation failure | Any 422 row-count/order failure in production | P1 | Backend + GIS leads |
| Blob upload failures | Edited GeoPackage upload errors >0 for production saves | P2 | Engineering on-call |
| Report version regression | Valid `GetValidationReport` or `GetAssessmentReport` version requests fail repeatedly | P2 | Backend on-call |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Before dev1 deployment | Prediction editing has no runtime flags in this branch; verify vector-first View Results, readiness, report `version`, and raw artifact immutability before promotion. |
| Disaster analysts | Release notes / Teams | Before testing enablement | Open View Results for trained or embedding models, use the pencil or `E` to edit predictions in place, save numbered versions, and download them. Version switching in the UI is not wired yet. |
| Product / data science | Design review | Before testing sign-off | Validation reads edited `damaged`; assessment still thresholds preserved `damage_pct_0m`, so manual overrides do not move assessment counts until a follow-up decision. |
| Partners | Release notes | At production enablement | Edited prediction GeoPackages may be shared as downloadable derived files; use `version=0` for raw report inputs and the default/newest version for edited report inputs. |

## Post-Rollout Checklist

- [ ] Decide whether to add runtime feature flags before broad production use.
- [ ] Decide whether UI version switching should refetch visualizer/report data.
- [ ] Decide whether `GetAssessmentReport` should count manual per-building
      overrides instead of only thresholding `damage_pct_0m`.
- [ ] Open follow-up issues for concurrent-save 409/ETag handling, API
      integration tests, Playwright/browser validation, classic row-loss risk,
      and raw `overture_id` producer columns.
- [ ] Temporary rollout monitoring removed or converted to normal dashboards.
- [ ] End-user docs updated with Visualizer edit-mode workflow and versioned
      report behavior.
- [ ] GitHub Pages docs rebuilt (`docs-deploy.yml`) if public docs changed.
- [ ] Docker Compose stack verified after release.
- [ ] `CHANGELOG.md` updated.
- [ ] Follow-up spec opened for publishing/downstream consumption if edited
      versions need active selection outside the current readers.
