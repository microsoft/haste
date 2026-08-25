# Impact Analysis: Prediction Editing

**Contents:** [Scope of Change](#scope-of-change) · [Azure Service Impact](#azure-service-impact) · [Dependency Analysis](#dependency-analysis) · [Risk Assessment](#risk-assessment) · [Performance Impact](#performance-impact) · [Security Impact](#security-impact) · [Compliance & Data Impact](#compliance--data-impact) · [Rollback Assessment](#rollback-assessment)

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library | `hastelib/src/hastegeo/core/models/`, `core/utils/`, `core/processors/`, `core/config.py` | add versioned sidecar metadata, shared sidecar helpers, save-time sidecar write, and backfill helper | high |
| REST API | `api/hastefuncapi/function_app.py` | extend `GetVisualizerResults`, `GetModelArtifact`, and `PutEditedPredictions`; preserve report defaults | high |
| Queue workers | `api/hastefuncqueues/function_app.py` | add idempotent backfill mode to prediction-edit prep | medium |
| React UI | `ui/src/Components/Visualizer/`, `ui/src/Components/ProjectManagement/` | add version selector, warnings, disabled states, dual-pane switching, and downloads | high |
| Blob Storage | existing artifact container | add `prediction_attrs_${modelId}_v${version}` blobs | medium |
| CI/CD / infra | `.github/workflows/...` | no expected workflow change; Playwright remains absent | low |

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Cosmos DB | Each `EditedPredictionVersion` stores one more URL; backfill updates existing version entries | low RU increase |
| Blob Storage | One compact sidecar JSON per edited version plus existing edited GeoPackage | proportional to version count and building count |
| Queue Storage | Backfill messages for historical versions | low, bounded by existing version count |
| Azure Functions | Save path does extra sidecar build/upload; artifact route resolves version metadata | medium during saves/downloads |
| Azure Batch / runners | Backfill and prep remain CPU-bound geospatial jobs | low to medium during backfill |
| Static Web Apps | UI downloads selected sidecar and GPKG through API routes | low hosting impact; browser memory unchanged per selected version |

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| Raw prediction GeoPackage (`Model.gpkgUrl`) | artifact | required | Raw map, saves, and raw downloads unavailable. |
| Raw prediction sidecar (`Model.predictionAttrsUrl`) | artifact | required for raw vector rendering | Raw selection is disabled or reports not ready. |
| Edited GeoPackage (`EditedPredictionVersion.gpkgUrl`) | artifact | required per version | Version cannot be downloaded or backfilled. |
| Versioned sidecar (`EditedPredictionVersion.predictionAttrsUrl`) | artifact | required per selectable version | Version must be disabled in the selector. |
| Source building footprints | artifact | required for sidecar building and row-order validation | Save/backfill fails visibly. |
| Shared sidecar helper | core code | lives in `hastegeo.core.utils` and is imported by the workflow | Divergent sidecar builders could render wrong classes. |
| `GetModelArtifact` auth/range streaming | API route | existing route | Downloads would regress to direct SAS URL behavior. |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| View Results UI | Selector changes map sidecar/version; downloads selected version | yes for UI behavior | update UI state/tests |
| Validation report | Continues newest-edited default; selector does not affect it | behavioral nuance | UI warning required |
| Assessment report | Continues newest-edited default but still thresholds preserved `damage_pct_0m` | behavioral nuance | product follow-up required |
| Existing edited versions | Need backfilled sidecars before selection | temporary window | run idempotent backfill for `0448` v1 and `5553` v1 in dev |
| External callers of `GetModelArtifact?kind=gpkg` | Omitted/`version=0` continues raw; positive `version` adds edited downloads | additive | none |
| Data publishing | No active-version pointer or publishing changes | no | follow-up spec if needed |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Versioned sidecar and edited GeoPackage disagree | medium | high | Build/store sidecar in the same save call path as the GPKG; do not advertise version until both URLs are recorded. | `backend-dev`, `gis` |
| Read path lazily generates sidecars and times out | medium | high | Run backfill through prediction-tiles job; `GetVisualizerResults`/`GetModelArtifact` return readiness/404 only. | `backend-dev` |
| Backfill leaves historical versions unselectable for a time | high | medium | Disable those versions and explain that sidecar prep is pending; run dev backfill for `0448` v1 and `5553` v1. | `backend-dev`, `ui` |
| Map version and reports disagree | high | medium | Record map-only decision; show explicit UI copy whenever selection is not newest. | `ui`, `backend-dev` |
| Only one swipe pane changes version | medium | high | Reset sidecar/source/feature-state for both renderers together; test the dual-pane case (`ui/src/Components/Visualizer/usePredictionFootprints.js:19-25`, `ui/src/Components/Visualizer/usePredictionFootprints.js:212-228`). | `ui` |
| Direct SAS URL download bypasses API auth/range path | medium | medium | Use `GetModelArtifact` for selector and history downloads; avoid URL rewriting (`ui/src/Components/ProjectManagement/ModelResultsButton.jsx:61-69`). | `ui`, `backend-dev` |
| Concurrent edited-version saves collide | medium | medium | Document no 409/ETag handling; add follow-up before multi-analyst editing. | `backend-dev` |
| Edited `damaged` moves Validation but not Assessment counts | high | medium | Keep documented as out of scope; product decision needed for Assessment semantics. | `backend-dev`, `gis` |
| Lack of browser/Playwright coverage misses visual regressions | high | medium | Add helper tests and manual evidence; record no Playwright config (`ui/package.json:6-15`, `ui/package.json:62-75`). | `ui-validation` |
| Classic prediction row-order risks remain | medium | high | Preserve row-order validation and keep producer-side fix as follow-up. | `gis` |

## Performance Impact

- **Save path:** `PutEditedPredictions` now writes one compact sidecar in addition
  to the edited GeoPackage. Large layers still drive memory and duration risk.
- **Backfill:** Backfill reads historical edited GeoPackages and footprints. It
  is bounded, idempotent, and should skip versions that already have sidecars.
- **Visualizer latency:** Version switching refetches the payload and selected
  sidecar. It does not rebuild artifacts.
- **Artifact streaming:** Versioned downloads use `GetModelArtifact`, preserving
  Range support and central download behavior (`api/hastefuncapi/function_app.py:1539-1585`).
- **Browser memory:** Only the selected sidecar is active. Footprint PMTiles are
  shared across versions.

## Security Impact

- [x] New API surface uses existing Function App auth and same-origin UI calls.
- [x] Versioned downloads stream through `GetModelArtifact`; no new direct blob
      SAS exposure is required.
- [x] Edited sidecars are derived disaster assessment data with the same
      sensitivity as raw prediction sidecars.
- [ ] New secrets or connection strings required? None expected.
- [ ] Component Governance scan implications? None unless implementation adds
      dependencies; the design reuses existing packages.

## Compliance & Data Impact

- [x] Geospatial data stays in the project artifact boundary.
- [x] Versioned sidecars are retained with edited GeoPackages unless approved
      cleanup tooling removes them.
- [x] Auditability improves because every selectable edited version has its own
      render data and downloadable GPKG.
- [ ] Release notes must explain map-only selection and report-newest behavior.

## Rollback Assessment

- **Reversibility:** Revert UI selector/downloads and API versioned artifact
  resolution if needed. The feature has no runtime flag.
- **Cosmos data:** `predictionAttrsUrl` on version entries is optional and safe
  for older code to ignore.
- **Blob data:** Versioned sidecars are additive derived artifacts. They can be
  left in storage after rollback.
- **Reports:** If default newest behavior causes confusion, callers can use
  `version=0` for raw reports while a product follow-up is evaluated.
- **Backfill:** Stop or drain the prep queue if backfill fails repeatedly; no
  read path depends on in-flight generation.
- **Estimated rollback time:** Previous-build redeploy for UI/API; less than 30
  minutes in the normal deployment path.
