# Stories: Versioned Prediction Editing

## Acceptance Criteria

| Story | Outcome | Acceptance criteria |
|---|---|---|
| PE-1 | Edit on the existing results map | Pencil/E toggles edit mode; no separate route or row-level editor button; both workflows supported. |
| PE-2 | Correct buildings efficiently | Class picker, click, Ctrl+box, right-click reset, arrow review and Enter work on both panes. |
| PE-3 | Adjust valid thresholds | Standard models expose live damage/unknown sliders, including binary-score datasets; embedding models do not. |
| PE-4 | Save auditable versions | New numbered GeoPackage plus sidecar; raw unchanged; no overwrite of a prior version; failures do not advertise success. |
| PE-5 | Select and download exact versions | Raw/saved selection switches both panes; post-save selection follows the returned version; proxy filenames identify versions. |
| PE-6 | Report on corrected predictions | Independent report selector defaults latest; raw/older accepted; edited class changes Assessment and Validation counts. |
| PE-7 | Use a stable accessible editor | Responsive/dark mode, keyboard help, scrollable non-shrinking controls, no double-click zoom while editing, visible errors. |

## Agent Assignment Map

| Story | Implementing agents | Validating agents |
|---|---|---|
| PE-1 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` |
| PE-2 | `ui` | `ui-validation` |
| PE-3 | `ui`, `gis`, `backend-dev` | `ui-validation`, `backend-validation` |
| PE-4 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` |
| PE-5 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| PE-6 | `backend-dev`, `gis`, `ui` | `backend-validation`, `ui-validation` |
| PE-7 | `ui` | `ui-validation` |

## Exclusions

No result-preparation queue, first-open generation, historical-data migration,
collaborative live editing, or edited-version publishing.
