# Data Model: Versioned Prediction Editing

## Version Artifacts

| Artifact | Contract |
|---|---|
| `Model.gpkgUrl` | Raw prediction, not replaced by editor saves |
| `Model.predictionAttrsUrl` | Raw matching attribute sidecar |
| `Model.editedPredictions` | Append-only metadata for saved numbered versions |
| Edited version GeoPackage | Original identity/geometry and scores plus effective class/override provenance |
| Edited version attributes | Derived from that exact edited GeoPackage |

Version entries include the number, creation/provenance metadata, thresholds,
edited count, GeoPackage URL, and `predictionAttrsUrl`. Save both artifacts
before advertising metadata and never replace existing saved-version artifacts.
Record the source `predictionRevision` and save request identity. A later raw
generation does not delete or reuse earlier version numbers. Historical
versions remain explicitly readable, but do not become the default edited
result for a different raw generation.

`Model.editedPredictions` is the history; there is no shadow authority, mirror,
reservation counter, or receipt ledger. A small per-model lock serializes edit
saves and cooperating result publications. The next visible version is one
greater than the maximum confirmed version.

Each upload attempt has a unique artifact namespace. Failed attempts remain
unreferenced; retrying does not overwrite their files or require a reserved
version record. A confirmed entry stores `clientRequestId` and its canonical
request fingerprint so an identical retry returns the same version.

`editedCount` counts effective classes changed from the original model, not
simply the number of explicit assignments. Model-class pins can therefore be
preserved without inflating the changed-building count.

## Prediction Semantics

Overrides are unique non-negative row IDs and one of Damaged, NotDamaged or
Unknown. Preserve source order, Overture identifiers and CRS. An edited class
takes precedence over threshold-derived class without overwriting the model's
continuous score. Both browser and backend use the same threshold boundaries.

Edited sidecars include explicit `predictionVersion`, `classes` for effective
analyst outcomes, `modelClasses` for the original producer classes, and
`overrideClasses` for explicit assignments (null where threshold-derived). Raw
stage-2 sidecars may omit `modelClasses`; their explicitly raw `classes` supply
that baseline. Right-click restores the model baseline, not the selected
version's prior edited class. A valid edit can classify a model's null/unscored
Unknown row without inventing a model score.
Save requests carry the complete sparse assignment snapshot, not only changes
since opening the editor. This preserves earlier assignments when resaving a
version. Right-click records an explicit model-class pin, even if the current
saved threshold would classify that row differently.

## Compatibility

Existing documents default to an empty edit list. Missing historical sidecars
do not trigger background work; history remains available and raw/saved
GeoPackages remain downloadable. No active-version pointer is added to shared
model metadata: map/report choices are per request.
An edit bound to a superseded raw generation is rejected rather than silently
rebasing row-ID overrides onto newer predictions.
Historical access is for saved positive versions. Raw `version=0` refers only
to the current generation; this feature does not add a historical raw catalog.

For reporting only, a legacy raw GeoPackage without `overture_id` can resolve
its complete positional IDs through immutable layer footprints. Require exact
count/order, integer IDs, CRS and score fields; verify explicit Overture IDs
when present. This does not mutate files or weaken new producer/editor input
validation.
