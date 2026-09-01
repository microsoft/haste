# Rollout Plan: Prediction Editing

**Contents:** [Rollout Strategy](#rollout-strategy) · [Deployment Targets](#deployment-targets) · [Feature Flags](#feature-flags) · [Rollout Phases](#rollout-phases) · [Rollback Plan](#rollback-plan) · [Monitoring & Alerting](#monitoring--alerting) · [Communication Plan](#communication-plan) · [Post-Rollout Checklist](#post-rollout-checklist)

## Rollout Strategy

**Type:** phased by environment deployment plus one-time backfill
**Target date:** TBD

The current design has no API or UI feature flag. Deploy first to dev/test,
verify new saves write GeoPackage + sidecar together, run idempotent backfill for
historical edited versions, then enable analysts to use the selector and
versioned downloads.

Rollout must account for a temporary backfill window: pre-existing versions with
no `predictionAttrsUrl` cannot be selected, and the UI must disable them with a
clear explanation rather than drawing an empty or raw-colored map.

## Deployment Targets

| Component | Deployment Method | Target |
|---|---|---|
| `hastelib` | pip install / Docker rebuild | Function Apps and queue workers |
| `hastefuncapi` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| `hastefuncqueues` | GitHub Actions `deploy-apps.yml` | Azure Functions |
| React UI | GitHub Actions `deploy-apps.yml` | Azure Static Web Apps |
| Backfill job | prediction-edit prep queue / maintenance command | Dev/test then production historical versions |

## Feature Flags

| Flag Name | Location | Default | Description | Kill Switch? |
|---|---|---|---|---|
| — | — | — | No prediction-editing feature flags are implemented in the current branch. | no |

## Rollout Phases

### Phase 1: Dev1 Environment — TBD

- **Target:** SWA `dev1` environment
- **Duration:** one sprint or until selector/download/backfill validation passes
- **Deployment:**
  1. Deploy core/API/queue changes.
  2. Deploy UI selector/download changes.
  3. Run edited-sidecar backfill for known dev models `0448` v1 and `5553` v1.
  4. Verify the selector disables any version whose sidecar remains missing.
- **Success criteria:**
  - [ ] New saves append `EditedPredictionVersion` with `gpkgUrl` and
        `predictionAttrsUrl`.
  - [ ] `GetModelArtifact?kind=gpkg&version=N` downloads edited versions through
        the API route, not direct blob URL rewriting.
  - [ ] `GetVisualizerResults?version=N` returns that version's
        `predictionAttrsUrl` and `isNewestPredictionVersion`.
  - [ ] Selecting raw or an older version changes the map only; reports still
        read newest and the UI says so.
  - [ ] Both swipe panes switch together with no stale colors.
  - [ ] Backfill is idempotent and skips already-sidecarred versions.
- **Rollback trigger:** Raw artifact mutation, repeated sidecar mismatch,
  versioned downloads bypassing `GetModelArtifact`, report regression, or browser
  crashes on representative layers.

### Phase 2: Testing Environment — TBD

- **Target:** SWA `testing` environment
- **Duration:** one response exercise or agreed analyst validation window
- **Success criteria:**
  - [ ] Analysts can select raw/newest/older versions on trained models.
  - [ ] Analysts can select raw/newest/older versions on embedding models.
  - [ ] Analysts can download selected versions and per-row versions.
  - [ ] Analysts understand map-only selection: Assessment and Validation report
        buttons continue to use newest.
  - [ ] Backfill status is clear for any historical version not yet selectable.
  - [ ] No regression from baseline UI lint/helper-test behavior.
- **Rollback trigger:** Sidecar/backfill failures above agreed threshold,
  confusing map/report semantics that block analyst use, or partial swipe-pane
  switching.

### Phase 3: Production — TBD

- **Target:** Production SWA + Function Apps
- **Federated credentials:** `fed-cred-main.json` (GitHub Actions OIDC)
- **Success criteria:**
  - [ ] Error rate and prep queue depth remain stable.
  - [ ] First production save creates both GeoPackage and sidecar.
  - [ ] First production versioned download uses `GetModelArtifact` and matches
        the requested version.
  - [ ] First production older-version map selection shows map/report warning.
  - [ ] Assessment `damage_pct_0m` gap is documented in release notes/support
        guidance.
- **Kill-switch follow-up:** If production requires runtime disablement, add the
  missing API/UI feature flags before broad enablement.

## Rollback Plan

| Step | Action | Owner | ETA |
|---|---|---|---|
| 1 | Redeploy previous UI build to remove selector/download affordances | `ui` | <1 hour |
| 2 | Redeploy previous API build if artifact version resolution regresses | `backend-dev` | <1 hour |
| 3 | Stop or drain `prediction-edit-prep-queue` if backfill fails repeatedly | `backend-dev` | <30 min |
| 4 | Verify raw `Model.gpkgUrl`, raw sidecar, and report defaults still work | `backend-validation` | <1 hour |
| 5 | Tell analysts that saved edited versions remain stored but older UI may not select/download them | `orchestrator` | <1 hour |

**Cosmos data rollback required?** no — `predictionAttrsUrl` on version entries is
optional and backward-compatible.
**Blob artifacts cleanup needed?** no for functional rollback — versioned
sidecars are additive derived artifacts.

## Monitoring & Alerting

### Key Metrics to Watch

| Metric | Source | Baseline | Alert Threshold |
|---|---|---|---|
| `GetVisualizerResults?version` error rate | Azure Functions / App Insights | new metric | >5% 5xx over 15 minutes |
| `GetModelArtifact` versioned download errors | Azure Functions / App Insights | new metric | repeated 4xx/5xx for valid versions |
| Save sidecar failures | App Insights logs | 0 | any repeated failure |
| Backfill queue depth | Azure Queue Storage metrics | 0 when idle | sustained growth for 30 minutes |
| Versions disabled due to missing sidecar | UI telemetry / logs | temporary during backfill | nonzero after backfill sign-off |
| Browser-side map switch errors | UI telemetry / support reports | 0 | repeated stale-pane or sidecar parse failures |

### Alerts to Configure

| Alert | Condition | Severity | Notify |
|---|---|---|---|
| Versioned visualizer failures | `GetVisualizerResults?version` 5xx rate >5% over 15 minutes | P2 | Engineering on-call |
| Versioned download failures | valid `GetModelArtifact` version requests fail repeatedly | P2 | Backend on-call |
| Backfill stalled | Queue depth rising and no completions for 30 minutes | P2 | Engineering on-call |
| Sidecar mismatch/failure | Any save advertises a version without sidecar | P1 | Backend + GIS leads |
| Partial swipe switch | Support/telemetry shows one pane on stale colors | P2 | UI lead |

## Communication Plan

| Audience | Channel | When | Message |
|---|---|---|---|
| Engineering team | GitHub PR / Teams | Before dev1 deployment | Versioned sidecars are derived data but must be written with the GPKG; read paths do not generate them. |
| Disaster analysts | Release notes / Teams | Before testing enablement | Use View Results to choose raw or edited map versions and download them. Reports still use newest, and the UI will say when the map differs. |
| Product / data science | Design review | Before testing sign-off | Map-only selection is intentional; Validation reads edited `damaged`, while Assessment counts still threshold preserved `damage_pct_0m`. |
| Partners | Release notes | At production enablement | Downloaded GeoPackages identify the selected raw or edited version and are served through authenticated API routes. |

## Post-Rollout Checklist

- [ ] Backfill completed for known historical edited versions or failures are
      tracked with disabled selector states.
- [ ] Decide whether to add runtime feature flags before broad production use.
- [ ] Decide whether `GetAssessmentReport` should count manual per-building
      overrides instead of only thresholding `damage_pct_0m`.
- [ ] Open follow-up issues for concurrent-save 409/ETag handling, API
      integration tests, Playwright/browser validation, classic row-loss risk,
      and raw `overture_id` producer columns.
- [ ] End-user docs updated with map-only version selection and download flow.
- [ ] Docker Compose stack verified after release.
- [ ] `CHANGELOG.md` updated.
- [ ] Follow-up spec opened for publishing/downstream consumption if edited
      versions need active selection outside the View Results map.
