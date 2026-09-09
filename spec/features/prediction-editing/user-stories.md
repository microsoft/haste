# Stories: Versioned Prediction Editing

## Acceptance Criteria

| Story | Outcome | Acceptance criteria |
|---|---|---|
| PE-1 | Edit on the existing results map | Pencil/E toggles edit mode; no separate route or row-level editor button; both workflows supported. |
| PE-2 | Correct buildings efficiently | Colored choices and click/Ctrl+box painting work on both panes. A compact Review filter and Left/Right arrows visit each class group; 1/2/3 annotate the highlighted building without changing that group. Keep reset/undo, without separate navigation/apply buttons or a detailed inspector. |
| PE-3 | Adjust valid thresholds | Raw and saved standard models expose one damage slider, including binary-score datasets. Manual assignments remain fixed, the loaded unknown threshold is preserved, and saving creates a new version. Embedding models have no slider. |
| PE-4 | Save auditable versions | New numbered GeoPackage plus sidecar; raw unchanged; no overwrite of a prior version; failures do not advertise success. Save is disabled for unchanged drafts. |
| PE-5 | Select and download exact versions | Raw/saved selection switches both panes; post-save selection follows the returned version; proxy filenames identify versions. |
| PE-6 | Report on corrected predictions | Independent report selector defaults latest; raw/older accepted; edited class changes Assessment and Validation counts. |
| PE-7 | Use a stable accessible editor | Responsive/dark mode, keyboard help, scrollable non-shrinking controls, no double-click zoom while editing, visible errors. |

## Agent Assignment Map

| Story | Implementing agents | Validating agents |
|---|---|---|
| PE-1 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` |
| PE-2 | `ui`, `backend-dev`, `gis` | `ui-validation`, `backend-validation` |
| PE-3 | `ui`, `gis`, `backend-dev` | `ui-validation`, `backend-validation` |
| PE-4 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` |
| PE-5 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| PE-6 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` |
| PE-7 | `ui` | `ui-validation` |

## Exclusions

No result-preparation queue, first-open generation, historical-data migration,
collaborative live editing, or edited-version publishing.
