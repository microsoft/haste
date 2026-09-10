# Design: Pretrained Catalog Inference

**Contents:** [Flow](#flow) - [Catalog](#catalog) - [API](#api) -
[Execution](#execution) - [Assets](#assets-and-runtime)

## Flow

Standard layer -> Inference -> compatible catalog selection -> new Model row ->
existing inference queue -> allowlisted adapter -> existing building aggregation
and visualizer output -> existing status/results/download/report controls.

Inference selection opens in a centered modal dialog. The catalog loads on
opening, with Retry only after a loading failure; no standalone reload control.

No training labels, target training checkpoint, or fine-tuning job is required.
The source catalog model is not modified when a run is started.
The existing results viewer frames catalog runs from the result COG's header
extent, not a training-label AOI. This transient display feature is never saved
as a label project and requires no pixel scan or result-preparation job.

## Catalog

Keep the global `model_catalog/index` document and unique `baseModelName`.
`CatalogModel` gains optional `capabilities` (`training`, `inference`) and a typed
`inferenceSpec`. Missing capabilities preserve existing training behavior.

`GetModelCatalog` can filter by `capability` and evaluate compatibility with an
optional `projectId`/`imageLayerId`. Entries expose `inferenceReady` and
`inferenceReadiness` (`ready`, `reason`, `detail`). Missing/incompatible recipes
are explained, not guessed. A model's provider/event tags are not substitutes for
its tensor input contract.

DINOv3 entries are inference-only. HASTE entries reuse the source model's
checkpoint and saved experiment recipe only when their identities still match.
External entries without `modelId` use `baseModelName` for selection/removal.

Catalog routes use the existing development-aware `AUTH_LEVEL`; production
function authentication and SWA roles remain enforced. Fetch failures render
errors and Retry, not an empty catalog or blank page.

## API

`PUT /api/PutRunCatalogInferenceQueueMessage`:

```json
{
  "projectId": "<GUID>",
  "imageLayerId": "<GUID>",
  "baseModelName": "<registered unique name>",
  "clientRequestId": "<UUID>",
  "name": "<optional run name>"
}
```

Return 202 with the created Model record. The record has `modelType=pretrained`,
`catalogModelName`, an inference recipe snapshot, and queued inference status.
Repeated delivery of the same logical request returns the same run; separate
intentional requests create different model IDs and artifact namespaces.

Validate project/layer association, standard workflow, prepared imagery,
footprints, permissions and catalog compatibility. Browser requests cannot
supply checkpoint URLs, Python module paths, or shell commands. Invalid input
returns 400; missing resources 404; incompatible state/request reuse 409; real
storage/execution failures remain errors.

Persist the run/configuration before publishing identifiers to the existing
queue. The worker reloads authoritative state and never replaces it with a sparse
or stale message. Progress, cancellation and output publication stay in the
existing inference lifecycle.

## Execution

Known adapters: `legacy_haste` and `dinov3_upernet`.

The generic `transformerinference` image hosts supported transformer adapters,
initially DINOv3. Its name is independent of model architecture; selecting a
different transformer checkpoint still requires an explicitly supported adapter.

The runtime configuration extends the existing YAML `inference` block with
`adapter`, optional `backbone_config_fn`, checkpoint/config SHA-256 values, and
an explicit `predictions_filename`. Existing `checkpoint_fn`, `patch_size`,
`padding`, `batch_size`, `output_subdir` and imagery paths remain usable.

Legacy HASTE uses its recorded native imagery, channel selection and
normalization with the current inference loader. DINOv3 uses
`imagery.rgb_fn`, RGB-tagged uint8 post-event imagery, ImageNet normalization
without clipping, and no pre-event image. Defaults are patch 512, padding 64,
batch 8, reader workers 2, prefetch factor 2.

Only the prediction-producing command changes in `run_workflow.py --step
inference`; aggregation and visualization remain shared. DINOv3's classes map
background 0 -> HASTE 1, undamaged 1 -> 2, damaged 2 -> 3, and NoData 255 -> 0.
Preserve valid background, NoData, CRS, grid and building identity. Missing
observations must not become confident undamaged buildings. Classification
overviews use nearest-neighbor resampling.
The results API explicitly requests PNG for both prediction overlays so
transparent backgrounds survive at every zoom. Automatic tile-format selection
can otherwise choose JPEG for fully valid source tiles and discard alpha.

Produce standard prediction/visualizer COGs, building GeoPackage, logs and run
provenance. Damage fractions are pixel-area fractions, not calibrated confidence.
Do not introduce the unmerged results/edited-version framework.

After successful inference, the existing `zip_artifacts` workflow packages the
run's outputs using a stable `zip-catalog-<project/request hash>` task. GPU
tasks use the corresponding `inf-catalog-` identity; identical request UUIDs
in different projects cannot collide in a shared runner. The same inference
poll advances this optional packaging phase; `ModelArtifacts` records its status
and a separate bounded failure count. Archive failures never downgrade successful
predictions, and repeated polls do not submit a second archive task.

## Assets and Runtime

Stage immutable, hashed checkpoint/config assets from controlled storage.
The DINOv3 source checkpoint is
`https://geospatialvisualizer.blob.core.windows.net/damage-assessments/model_checkpoints/xview2_dinov3_upernet_any-last.ckpt`.
Actual architecture and `any` damage grouping must be established before use.
Use restricted checkpoint loading and strict state-dictionary matching.

Preserve MIT attribution for adapted code and DINOv3 asset license notices.
There is no new blanket licensing approval process. Obtain authorized offline
configuration; do not embed tokens or download gated model code during jobs.
Pin a compatible ML stack. Isolate DINOv3 dependencies if necessary rather than
silently breaking existing training.
