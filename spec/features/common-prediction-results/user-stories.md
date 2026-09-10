# Stories: Common Prediction Results

## Acceptance Criteria

| Story | Analyst outcome | Acceptance criteria |
|---|---|---|
| CR-1 | View either workflow's predictions | Both model rows navigate to the same Visualizer; matching vectors appear on both swipe panes. |
| CR-2 | Results ready when predictions complete | Interactive save generates attributes; standard inference emits and uploads attributes in its existing job. |
| CR-3 | Trust classes and identity | Row/count mismatches fail explicitly; binary standard-model scores do not change its flavor; repeat prediction uses fresh attributes. |
| CR-4 | Understand unavailable results | Cleared/empty interactive predictions disable results; old missing sidecars show actionable guidance without queuing work. |
| CR-5 | Access protected artifacts | PMTiles, attributes, and downloads use the API proxy; mismatched model/layer requests are rejected. |

## Agent Assignment Map

| Story | Implementing agents | Validating agents |
|---|---|---|
| CR-1 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` |
| CR-2 | `gis`, `backend-dev` | `backend-validation` |
| CR-3 | `gis`, `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| CR-4 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |
| CR-5 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` |

## Exclusions

Versioned editing is the next stacked feature. The results-preparation queue
and first-open backfill from #136 are explicitly excluded.
