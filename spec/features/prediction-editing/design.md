# Design: Versioned Prediction Editing

**Contents:** [Architecture](#architecture) - [Interaction](#interaction) -
[API](#api) - [Versions and reports](#versions-and-reports) -
[Failure handling](#failure-handling)

## Architecture

Build on [eager shared results](../common-prediction-results/design.md). Adapt
the final UI and artifact semantics from #136; its earlier specification text
is not authoritative where it differs from the final implementation. In
particular, reports allow explicit version selection and Assessment must count
analyst overrides rather than the preserved model score.

Geometry remains shared per layer. Raw and edited predictions each have a
matching attribute sidecar. Saving an edit generates that sidecar immediately;
there is no prediction-preparation queue, route, or first-open job.

## Interaction

Enter edit mode using the pencil beside Back or E, without changing routes.
Use a compact Fluent UI class-picker panel and vector-first Azure Maps swipe
view. Class choices use the same semantic colors as the prediction legend and
map. Keep the existing version selector and download control outside the editor;
do not duplicate version history inside the panel.

| Input | Behavior |
|---|---|
| Class button | Choose Damaged, NotDamaged, or Unknown |
| Click footprint | Apply the active class |
| Ctrl+drag box | Paint buildings inside the box |
| Right-click footprint | Restore that building's model-predicted class |
| Review filter and Left/Right arrows | Highlight and center each building in the chosen class group |
| 1/2/3 with a highlighted building | Annotate it as Damaged/NotDamaged/Unknown without changing the review group |
| Damage threshold slider | Reclassify unassigned buildings in raw or saved standard-model results |
| Embedding model | No threshold sliders; discrete class editing remains available |

Both swipe panes share classes and manual assignments. Disable double-click zoom only
while editing; preserve panning and wheel zoom. Use the same responsive layout,
dark-mode Fluent tokens, and non-shrinking scroll-panel controls as #136.
Retain the results page's removal of imagery-adjustment sliders.
Saved standard-model versions can be used as the starting point for a new damage
threshold. Recompute only buildings without explicit manual assignments, using
their preserved model scores. Keep the loaded unknown/cloud threshold unchanged;
there is no separate cloud-threshold control. Undo restores the loaded draft,
including its thresholds and assignments. Save creates a new version and never
changes the version used as its base.

The panel contains class choices with counts, the standard-model damage slider,
a compact Review filter, one undo action, and Save/Done. There are no separate
Previous/Next buttons, selected-building inspector, or Apply/Reset-selected
controls. Class buttons choose the mouse-painting class and clear the keyboard
highlight. Review navigation is independent of that painting class.

Review uses cached tile locations where available. An unloaded building is
located by an exact, single-building request through the existing footprint
GeoJSON endpoint; verify its row and Overture IDs before centering it. Never
sample the review group, skip unloaded buildings, or fetch the whole PMTiles
archive for navigation.

## API

Keep HASTE route/auth conventions. Validate body schemas with Pydantic; keep
plain-data operations in `hastegeo`, not in HTTP wrappers.

| Endpoint | Request | Response |
|---|---|---|
| `PUT /api/PutEditedPredictions` | Identifiers, generation/base version, request ID, thresholds, unique row-ID/class overrides | Saved version number, GeoPackage URL, attribute URL, edited count |
| `GET /api/GetEditedPredictionVersions` | Project/model identifiers | Saved version metadata, newest first |
| `GET /api/GetVisualizerResults` | Optional `version` | Selected raw/edited artifacts, thresholds, available versions, and `editReadiness` |
| `GET /api/GetModelArtifact` | `kind=gpkg` or `prediction_attrs`, optional `version` | Protected artifact stream and unambiguous filename |
| `GET /api/GetValidationReport` | Optional `version` | Metrics for the selected prediction source |
| `GET /api/GetAssessmentReport` | Optional `version` | Assessment for the selected prediction source |

Artifact endpoints default to raw when version is omitted. Visualizer/report
endpoints default to the latest saved edit for the current prediction
generation, or raw when that generation has no edits.
`version=0` explicitly requests raw; positive values request that saved version.
Malformed identifiers/versions/classes return 400; missing models, artifacts or
versions return 404. Model/layer mismatches must be rejected. Preserve the
existing authenticated/SWA principal checks and never fall back to direct
storage downloads.

Example save request:

```json
{
  "projectId": "11111111-1111-4111-8111-111111111111",
  "imageLayerId": "22222222-2222-4222-8222-222222222222",
  "modelId": "5557",
  "predictionRevision": "33333333-3333-4333-8333-333333333333",
  "baseVersion": 0,
  "clientRequestId": "44444444-4444-4444-8444-444444444444",
  "threshold": 0.0,
  "unknownThreshold": 0.0,
  "overrides": [{"id": 7, "class": "Damaged"}]
}
```

`baseVersion` identifies the displayed source, not a requirement that it be the
newest saved version. `predictionRevision` is a generation precondition.
There is no separate edit session or edit-session endpoint. Entering edit mode
uses the already-loaded visualizer metadata and validated attributes. The save
endpoint revalidates the current generation, ownership and source availability.
The UI disables Save until thresholds or explicit assignments differ from the
loaded draft; merely choosing an active class does not make a draft dirty.
`clientRequestId` identifies a save attempt so a lost-response retry does not
create duplicate visible versions. Return structured 409 errors for a changed
source, write contention, or reuse of a request ID for a different payload.
Replay identity is stored on the confirmed `Model.editedPredictions` entry,
not in a separate receipt store. Each attempt writes unique artifact paths.

## Versions and Reports

Write the edited GeoPackage and its sidecar before appending version metadata.
Keep `Model.gpkgUrl` as the raw pointer. Record immutable version metadata and
protect existing artifacts from replacement by a repeated or conflicting save.
Do not advertise a version whose sidecar failed to write.

After saving, reload the returned version and update the active selector,
rendered attributes, and download target together. Merely refreshing the option
list is insufficient. Clear renderer-specific feature state before replacing
the source, and reset edit baselines in both map instances.

Raw and saved downloads always go through `GetModelArtifact`, including a
model with no saved versions. Model rows open a version-choice dialog when
edits exist. Validation and Assessment have independent "Report on" selectors
defaulting to the newest saved version.

Assessment uses `edited_class` where present. Preserve model probabilities as
provenance, but use 0/1 analyst outcomes for corrected rows and a single operating
point for edited-version precision/recall rather than sweeping a nonexistent
continuous analyst score.
Exclude Unknown predictions from binary confusion metrics and expose their
count separately; keep the ground-truth sampling cohort used by population
estimation independent of that exclusion. Raw report threshold defaults remain
unchanged; saved categorical decisions do not change when a report threshold
is adjusted.

## Failure Handling

Display save/download/load errors and preserve unsaved edits when saving fails.
Handle conflict responses without claiming a new version was saved. An older
saved version without attributes remains downloadable, but its map selection
is disabled with explicit missing-artifact guidance; opening it does not enqueue
a backfill. This implementation does not migrate the user's local projects.

Assessment may return a successful partial report with aggregate predictions,
a population estimate, and a diagnostic explaining unavailable label-based
metrics. Display those aggregates and the diagnostic together; HTTP failures
and error-only responses remain errors. Validation uses the API's
`excludedUnknownPredictions` count. Publication descriptions explicitly request
raw version zero, matching the raw-only published dataset. Results menus enable
saved-version viewing only when the server reports complete readiness.
