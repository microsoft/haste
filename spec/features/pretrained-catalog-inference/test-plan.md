# Test Plan: Pretrained Catalog Inference

**Contents:** [Contracts](#contracts) - [Runtime](#native-runtime) -
[UI and deployment](#ui-and-deployment) - [Evidence](#current-evidence)

## Contracts

Cover catalog dev/production auth bindings, empty/error states, external
identity handling, compatible/unsupported recipes, input validation, unique
runs, duplicate delivery, stale polls, cancellation and publish-after-upload.
No request may execute fine-tuning or require target training labels.

## Native Runtime

Adapt the reference raster tests for RGB8/color tags, masks, reflected edges,
small images, core stitching, channel normalization, output classes and COG
metadata. Compare actual checkpoint GPU output to the pinned reference where
available. Check restricted loading, hashes and offline configuration.

Prove legacy HASTE inference equivalence and stable building identity/NoData
semantics. Verify readable standard GeoPackages and COGs, not just file presence.

## UI and Deployment

Exercise layer row/card actions, compatible choices, error/retry, distinct model
rows, progress/cancel and existing result actions. Use existing Node, Python,
build/lint and deterministic browser tools. Validate local GPU and Azure Batch;
report unavailable cloud access as a blocker, not a success.

## Current Evidence

Parent-owned backend selectors passed 177 tests across catalog
submission/import/archive handling, stable runner identities, cancellation,
wrapped storage failures, legacy API/Batch regressions, and GeoPackage report
joins. This includes real tiny GeoPackages for source-ID joins and NoData
report counts; checkpoint and GPU execution are not covered by those fixtures.

Catalog production bindings were inspected with development mode disabled:
all four catalog/submission HTTP triggers retain function-level authentication.
The final focused catalog/job/viewer/narrative selectors passed 53 Node tests;
the UI specialist's full Node run passed 141. Changed-file lint and the
production UI build passed. Repository-wide UI lint retains unrelated baseline
diagnostics. Hatch wheel building passed; the Hatch test environment lacks its
conda environment plugin, so targeted backend tests used the configured `haste`
conda environment directly.

Actual-checkpoint acceptance passed 93 native tests on the isolated Python 3.10,
Torch 2.10/CUDA image: 257 tensors, logits, classes and masks matched the pinned
reference exactly on the recorded fixtures. Full-scene DINOv3 run 1072 then
completed through the API, queue, GPU runner, common postprocessing and archive
workflow. Its 47,633,331 pixels preserve the input grid and mask, and its output
contains real background, undamaged and damaged predictions.

Legacy run 9545 matches source run 4204 at every pixel on the same grid.
Both new runs have no training job and retain all 1,496 building rows in reports.
Running cancellation of separate run 6156 stopped its GPU container in 5.5
seconds without publishing result links. All six pre-existing model snapshots
remained unchanged.

Real-browser checks covered both completed models, row/card inference controls,
fresh narrow entry/reload, desktop rendering, map disposal and no-label reports.
The final shipped stack was exercised on ports 4280/7071 without transport
remapping: DINOv3 desktop tiles returned 24/24 HTTP 200, and fresh narrow entry
and reload each returned 8/8. No blocking browser errors remained.
Azure Maps' placeholder-development metadata 401s are nonblocking; real
credentials remain necessary for subscription basemaps.

High-zoom raw-overlay transparency was reproduced at zooms 18 and 20:
extensionless requests returned JPEG and made background pixels opaque black.
Explicit PNG requests retained 45,963 and 37,259 transparent pixels in the same
256x256 tiles. The RGBA building-overlay comparisons were pixel-identical.
The results API now explicitly requests PNG for both overlays; existing rasters
and inference results require no regeneration.

No live Azure Batch account/pool was available for execution. Batch identities,
resource/output contracts, deployment wiring and Bicep compilation were checked;
these are not a claim that a cloud GPU job ran. No cloud deployment, push or PR
was performed.
