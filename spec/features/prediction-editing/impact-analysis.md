# Impact Analysis: Prediction Editing

**Contents:** [Scope of Change](#scope-of-change) · [Azure Service Impact](#azure-service-impact) · [Dependency Analysis](#dependency-analysis) · [Risk Assessment](#risk-assessment) · [Performance Impact](#performance-impact) · [Security Impact](#security-impact) · [Compliance & Data Impact](#compliance--data-impact) · [Rollback Assessment](#rollback-assessment)

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library | `hastelib/src/hastegeo/core/models/`, `hastelib/src/hastegeo/core/processors/`, `hastelib/src/hastegeo/core/utils/`, `hastelib/src/hastegeo/core/config.py` | modified / new | high |
| REST API | `api/hastefuncapi/function_app.py` | new endpoints; modified artifact dispatch | medium |
| Queue workers | `api/hastefuncqueues/function_app.py` | new prep trigger | medium |
| React UI | `ui/src/Components/...` | new route/editor; modified model rows | high |
| Docker config | `docker/training/` | no new package expected; uses existing `tippecanoe` in training env | low |
| CI/CD / infra | `.github/workflows/...`, `infra/modules/functions.bicep` | no workflow change; explicit Bicep app-setting parity for the prep queue was skipped to avoid `infra/main.json` drift | low |

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Cosmos DB | Model and ImageLayer documents gain optional fields; Model appends small version records | low RU increase per session/save |
| Blob Storage | Stores PMTiles, sidecars, and one edited GeoPackage per save | proportional to footprint count and version count |
| Queue Storage | Adds prep messages for missing PMTiles/sidecars | low; bursty when editors first open layers |
| Azure Functions | Adds three HTTP routes and one queue trigger | low to medium CPU/memory during save and metadata reads |
| Azure Batch | Reuses existing runner/training image path for `tippecanoe` prep | low; CPU-bound tile jobs may occupy existing nodes |
| Static Web Apps | Adds one route and larger client-side editing workflow | low hosting impact; browser memory is the main concern |

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| Raw prediction GeoPackage (`Model.gpkgUrl`) | artifact | available after prediction | Editor cannot open or save. |
| Source building footprints (`ImageLayer.buildingFootprintsUrl`) | artifact | available after imagery prep | Cannot derive `overture_id` or validate row-order mapping. |
| `tippecanoe` in training image | container tool | available only in training env | PMTiles cannot be generated from Functions inline (`docker/training/env/env.yml:11`). |
| PMTiles JS support | UI dependency | already present | Editor map cannot stream full geometry efficiently. |
| Azure Maps | UI mapping | available in app | Editor loses primary visual interaction surface. |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| `hastefuncapi` callers | New endpoints and artifact kinds; existing endpoints unchanged | no | no |
| React model rows | New Edit action and stricter embedding edit gating | no | no |
| Existing Cosmos documents | Optional fields absent until touched/backfilled | no | no blocking migration |
| Assessment report | Not changed; continues using raw `Model.gpkgUrl` | no | follow-up spec required to consume edits |
| Validation report | Not changed; continues using raw `Model.gpkgUrl` | no | follow-up spec required to consume edits |
| Data publishing | Not changed; edited versions not publishable in v1 | no | follow-up spec required |
| Visualizer | Not changed; edited versions not shown in v1 | no | follow-up spec required |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Positional row-order invariant breaks Overture id mapping | medium | high | Assert row count and row order in prep/save tests; never sort or spatial-join edited output; write explicit `overture_id` for audit. | `gis` |
| Editor default threshold and `GetAssessmentReport` default differ | medium | medium | Document the current split: editor defaults to `0.0` to reproduce raw stored predictions, while reports still default to `0.1`; add product follow-up if this confuses users. | `backend-dev` |
| Large layers exceed memory in tile prep or edit application | medium | high | Keep browser geometry in PMTiles; measure whole-GPKG reads; add performance tests; move save to async if needed. | `backend-dev`, `gis` |
| HTTP handler tries to run `tippecanoe` inline | low | high | Keep PMTiles generation in `prediction-edit-prep-queue`; test absence of inline generation path. | `backend-dev` |
| Embedding `gpkgUrl` is treated as a full prediction set after Clear labels | high | medium | Gate on `predictedBuildingCount > 0` and set `predictedAt` only after non-empty predictions. | `ui`, `backend-dev` |
| Edited artifact overwrites raw output | low | high | Never write to `Model.gpkgUrl`; use `EDITED_PREDICTIONS_GPKG` with version in the name and append metadata. | `backend-dev` |
| UI hard-coded colors fail dark mode | medium | medium | Require `makeStyles` + Fluent tokens; add UI review checklist item. | `ui` |
| UI lint remains red because of existing ESLint 9 flat-config mismatch | high | medium | Treat CI gate as no regression from baseline; record baseline failure and require targeted UI tests. | `ui-validation` |
| Concurrent edited-version saves collide | medium | medium | Current implementation has no 409/ETag conflict handling; add optimistic concurrency before relying on simultaneous multi-analyst saves. | `backend-dev` |

## Performance Impact

- **API latency:** `GetPredictionEditSession` is read-only and does not enqueue,
  but it downloads the raw prediction GeoPackage to detect flavor and count
  rows. `PutPreparePredictionTilesQueueMessage` performs the queue request.
  `PutEditedPredictions` reads and writes a full GeoPackage in v1, so large
  layers may approach function timeout or memory limits.
- **Queue throughput:** New prep jobs are CPU and I/O bound. They should be
  idempotent and skip PMTiles or sidecar generation when artifacts already
  exist.
- **Tile serving:** The editor uses static PMTiles artifacts, not TiTiler for
  vector tiles. Tile serving load shifts to Blob/download bandwidth.
- **Batch compute:** No GPU is needed. Existing training-image jobs may consume
  CPU on the current runner pool while generating PMTiles.
- **Storage I/O:** Each editor open may download PMTiles and sidecar data; each
  save writes a full edited GeoPackage.

## Security Impact

- [x] New API endpoints exposed? Use existing `func.AuthLevel.FUNCTION` and SWA
      auth pattern.
- [x] New data classification handled? Edited predictions are derived disaster
      assessment geospatial data, same sensitivity as raw model outputs.
- [ ] MSAL/Entra ID auth changes? None expected.
- [ ] New secrets or connection strings required? None expected.
- [ ] CORS configuration changes in SWA? None expected.
- [ ] New federated credentials needed? None expected.

## Compliance & Data Impact

- [x] Geospatial data sovereignty concerns? Same as raw project artifacts;
      edited versions must stay in the project storage boundary.
- [x] Partner data sharing agreements affected? No external sharing in v1;
      downloads are existing-authenticated artifact access.
- [x] New data retention requirements? Versioned edited GeoPackages increase
      retained derived artifacts; retention follows project artifact retention.
- [x] Audit logging for new operations? Save logs should include project,
      model, version, editor identity when available, and edited count.
- [ ] Component Governance scan implications? None unless implementation adds
      dependencies; current design reuses existing packages.

## Rollback Assessment

- **Reversibility:** fully reversible for runtime behavior by disabling feature
  flags; persisted optional metadata and blobs can remain safely.
- **Cosmos data:** Old code ignores optional `editedPredictions`,
  `predictedBuildingCount`, `predictedAt`, `predictionAttrsUrl`,
  `predictionTilesJob`, `predictionTilesStatus`,
  `predictionTilesStatusMessage`, and `footprintPmtilesUrl`. Cleanup is
  optional, not required for rollback.
- **Blob data:** Edited GeoPackages, sidecars, and PMTiles are additive derived
  artifacts. They can be deleted by approved maintenance tooling if needed.
- **API:** New endpoints and artifact kinds are backward-compatible. Existing
  endpoint contracts are unchanged.
- **Estimated rollback time:** Immediate feature-flag disable; less than 30
  minutes to redeploy a reverted UI/API if required.
