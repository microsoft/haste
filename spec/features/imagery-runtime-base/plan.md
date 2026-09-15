# Plan: imagery runtime base recovery

## Execution

| Task | Story | Agent | Status |
|---|---|---|---|
| Replace the expired base and isolate worker dependencies | US-001 | `backend-dev` | Complete |
| Preserve ACR builder compatibility | US-001 | `backend-dev` | Complete |
| Reject false Python-version tokens and add regression coverage | US-001 | `backend-dev` | Complete |
| Align container documentation and story assignments | US-001 | `backend-dev` | Complete |
| Add native raster, vector, and GDAL-policy coverage | US-002 | `backend-dev`, `gis` | Complete |
| Run build/dependency regressions for the review corrections | US-001 | `backend-validation` | Complete; 88 tests passed |
| Validate the native runtime on the selected base | US-002 | `backend-validation` | Prior evidence recorded in [README](README.md#local-results) |

## Validation

The build/dependency suite covers supported image references, rejection of
unrelated names, Python/GDAL pin consistency, and ACR-compatible installation.
The native runtime suite exercises real raster and vector operations offline.
Keep prior validation evidence distinct from checks performed on a new head.

## Rollout boundary

The [design](design.md#rollout-boundary) retains the curated base's Preview
caveat and the separate deployment approval. This maintenance change does
not include the prediction-editing feature, AML backend, or release-pipeline
changes.
