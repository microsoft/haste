# Design: Common Prediction Results

**Contents:** [Architecture](#architecture) - [Artifacts](#artifacts) -
[API](#api) - [User interface](#user-interface) - [Failure handling](#failure-handling)

## Architecture

```text
Interactive prediction save ------> GPKG + prediction attributes
Standard inference step ----------> GPKG + prediction attributes
                                              |
                           existing artifact upload/completion
                                              |
                                  model result metadata
                                              |
Layer footprint cache -> #183 tiles -> View Results (read-only)
```

Use the existing processors and artifact storage abstractions described in
[the architecture](../../architecture/overview.md). Footprint generation remains
layer-scoped. The embedding feature-vector sidecar remains model-scoped and is
not the results attribute sidecar.

The standard job's `run_workflow.py` creates attributes immediately after
`merge_with_building_footprints.py` produces building predictions. The pixel
segmentation loop in `inference.py` does not yet have building-level rows.
`Inference.prediction_attrs_filename` supplies the safe JSON basename and
`Inference.prediction_revision` binds the output to the accepted generation.
The existing Local/Batch output upload includes the sidecar.

For interactive results, `write_building_predictions` performs local GeoPackage
and sidecar creation; the API's core orchestration owns generation/publication.
Both paths use `core.utils.prediction_attrs.write_prediction_attrs`.

## Artifacts

Adapt the columnar prediction-attribute format from #136: stable row identifiers,
Overture identifiers, class labels, and damage/cloud scores. Match the layer
footprint row identity exactly; reject inconsistent counts or identifiers rather
than silently coloring the wrong building. Preserve GeoPackage row order and CRS.

Interactive prediction creation writes a sidecar before advertising success.
Standard inference creates its sidecar as part of the existing inference job;
completion publishes both artifact pointers together. Regenerating predictions
must never leave readiness pointing at attributes from an earlier prediction.

Determine prediction flavor from the model or producer schema, never from
whether scores happen to contain only zero and one.

Keep every source footprint row, including out-of-raster or unscored rows;
represent the latter as Unknown with null scores. Do not drop and renumber rows.
Use a new prediction-generation token and immutable output namespace when
replacing raw predictions. Publish the two uploaded artifact pointers together
and reject obsolete completions. Artifact URLs include generation identity so
same-model regeneration cannot reuse a cached older sidecar.

## API

Keep existing HASTE action-style route names and `AUTH_LEVEL` conventions rather
than introducing a parallel REST naming convention.
Pydantic validates HTTP requests and inference configuration. Native GeoPackage
cells and cross-row geometry identity are checked by the shared geospatial
utilities after Fiona/GDAL decoding; those checks are not a second HTTP schema.

| Endpoint | Contract |
|---|---|
| `PUT /api/PutBuildingPredictions` | Existing validated prediction request; persist count/time and matching attributes with the GeoPackage. Empty predictions clear result readiness. |
| `GET /api/GetLayerModelsDetails` | Include server-derived readiness, consistently across both model types. |
| `GET /api/GetVisualizerResults` | Existing identifiers; return imagery and API-relative footprint/attribute artifact URLs for either workflow. No generation or enqueue. |
| `GET /api/GetModelArtifact` | Add model-scoped `kind=prediction_attrs`; retain layer-scoped `kind=footprint_pmtiles` from #183 and proxy GeoPackage downloads. |

Artifact requests with a model and an explicit image-layer ID must refer to that
model's layer. Preserve project authorization and identifier validation.
Malformed requests return 400, missing resources/artifacts return 404, and
unexpected storage failures remain errors. Do not return a direct storage URL
as a fallback.

The visualizer adds `flavor`, `supportsThreshold`, `defaultThreshold` (zero),
`defaultUnknownThreshold` (zero), `buildingCount`, `predictionRevision`,
`predictionsReady`, and `predictionsReadiness` with `reason`/`detail`. Preserve
zero counts. Keep raw-download availability separate from render readiness.
The read-only stage has no saved prediction versions.
Publishing and raw downloads use raw-output availability, not the viewer's
additional sidecar/PMTiles requirements. An explicit zero-count clear is
unavailable to all prediction consumers.

## User Interface

Use the existing Visualizer route for both workflows. Share one PMTiles protocol
registration with the Interactive Labeler and color footprint vectors through
feature state on both Azure Maps swipe panes. Preserve standard-model raster
overlays where available; embedding results do not invent a raw raster layer.

The read-only stage has no edit button, save/version API, threshold editor, or
prediction-preparation request. It may report that layer tiles are still being
built, but does not start that work. Historical results missing a sidecar explain
that predictions/inference must be rerun.

## Failure Handling

- Propagate aborted downloads as cancellation, not a missing-artifact error.
- Bound attribute/archive downloads and validate the sidecar before rendering.
  The viewer limits JSON attributes to 64 MiB and PMTiles to 1 GiB, with a
  visible error rather than silently truncating the prediction set.
- Do not publish a ready result if sidecar generation/upload fails.
- The Interactive Labeler confirms writes before showing saved/cleared success.
  Conflicts and partial multi-write clears remain explicit failures, not success
  statuses beneath an error dialog.
- Clear feature state before removing/replacing a reused map source.
- Keep empty or cleared interactive predictions unavailable even if a valid
  empty GeoPackage exists.
- Opening results does not mutate metadata, create queues, or submit jobs.
