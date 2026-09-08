# Design: Common Prediction Results

## Production

`PutBuildingPredictions` writes the interactive GeoPackage and attributes in
one call. Standard `run_workflow.py` writes attributes immediately after the
building-footprint merge, inside its existing inference job. Both use
`write_prediction_attrs`; the existing output upload includes the JSON.

Store `gpkgUrl`, `predictionAttrsUrl`, `predictionRevision`,
`predictedBuildingCount`, and `predictedAt` directly on `Model`. Write a new
output pair before replacing these fields; failure leaves the previous
successful pair intact. Empty interactive predictions explicitly clear the
pointers/count. The revision identifies matching output and browser freshness,
not a separate lifecycle record or a saved edit version.

Preserve footprint order, row IDs, Overture IDs, and CRS. Retain unscored rows
as Unknown/null instead of dropping and renumbering them. Reject inconsistent
identities/counts. Determine flavor from producer/schema, not binary scores.
The columnar JSON contract remains:

```json
{"schemaVersion":1,"predictionRevision":"output-id","flavor":"inference","n":2,
 "ids":[0,1],"overtureIds":["building-a","building-b"],"damage":[0.25,null],
 "unknown":[0,null],"damaged":[1,0],"classes":["Damaged","Unknown"]}
```

## Reads and Viewer

| Endpoint | Contract |
|---|---|
| `PUT /api/PutBuildingPredictions` | Existing validated prediction request; persist count/time and matching attributes with the GeoPackage. Empty predictions clear result readiness. |
| `GET /api/GetLayerModelsDetails` | Include server-derived readiness, consistently across both model types. |
| `GET /api/GetVisualizerResults` | Existing identifiers; return imagery and API-relative footprint/attribute artifact URLs for either workflow. No generation or enqueue. |
| `GET /api/GetModelArtifact` | Add model-scoped `kind=prediction_attrs`; retain layer-scoped `kind=footprint_pmtiles` from #183 and proxy GeoPackage downloads. |

Keep existing auth and strict request/owner validation. Model/layer mismatch is
an error. GETs do not generate artifacts or enqueue work. The viewer receives
protected URLs, flavor, count, revision and readiness, with zero-default
classification thresholds. Downloads never fall back to direct blob URLs or
add unsupported cache-busting parameters.
Raw GeoPackage downloads preserve the model's authoritative inference basename
when safe for a response header, with a model-specific fallback. Rendered
footprints require an exact, non-empty Overture ID match before any feature
state is written. Both labeling and results canonicalize the protected
footprint URL by project/layer, independent of model ID and query ordering.

Both workflows use the same Visualizer route, shared PMTiles protocol and
two-pane feature-state renderer. Keep optional standard rasters, legends,
theme/mobile controls and cancellation handling. Bound JSON downloads to 64 MiB;
clear old feature state before replacing sources.

Both the Visualizer and Interactive Labeler read PMTiles through the standard
HTTP-backed source: fetch the header/root directory, then the directories and
tiles needed by the viewport. Never preload the whole archive or fall back to a
full download when byte serving fails. Cache archives by the protected
project/layer URL, independent of model ID or query parameter order. Keep
initial-load cancellation and per-range timeouts.

The artifact endpoint supports `Range`, `206 Partial Content`, `Content-Range`
and `ETag`. Same-origin SWA routing keeps its existing authentication. Local
cross-origin API access must allow `Range` and expose `Content-Range`, `ETag`,
`Accept-Ranges` and `Content-Length` to browser JavaScript. Do not assume a SWA
range limitation; verify the deployed proxy with an authenticated range GET.

## Boundaries and Rollout

Keep existing metadata/storage and inference control mechanisms. This feature
does not add global CAS, raw-result locks, mirrors, tombstones, or a transactional
job outbox. Only result publication/freshness checks belong in its producer paths.
Editor-specific version-save coordination belongs in the following PR.

Deploy the inference image with the API/core/UI. Existing raw GeoPackages remain
downloadable/reportable without viewer attributes. Missing sidecars require an
explicit prediction/inference rerun, never first-open backfill. No project-data
migration or running-stack changes are part of this implementation.
