# Plan: Common Prediction Results

## Implementation

| Task | Agent | Stories | Status |
|---|---|---|---|
| Remove shadow metadata/lifecycle machinery; retain direct Model result writes | `backend-dev` | CR-2 to CR-5 | complete |
| Consolidate raw attribute/GeoPackage helpers without weakening identity checks | `gis` | CR-2, CR-3 | complete |
| Preserve the shared viewer and protected downloads | `ui` | CR-1, CR-4, CR-5 | complete |
| Validate paired writes, clear/failure/freshness, ownership, and existing inference wiring | `backend-validation` | CR-2 to CR-5 | complete |
| Confirm unchanged viewer contracts, cancellation and download behavior | `ui-validation` | CR-1, CR-4, CR-5 | complete |
| Document caller-supplied revision IDs in the worker and make the specification self-contained | `backend-dev` | CR-2, CR-3 | complete |
| Resolve protected download URLs and filenames with one model read | `backend-dev` | CR-5 | complete |
| Verify single-read downloads, ownership, stale revisions, and safe filenames | `backend-validation` | CR-5 | complete |
| Reuse the model readiness projection in project, layer, and model-list responses | `backend-dev` | CR-1, CR-4, CR-5 | complete |
| Preserve contracts consumed by the stacked prediction editor | `backend-dev`, `ui` | CR-1, CR-3, CR-5 | complete |
| Share Results actions across standard and embedding rows | `ui` | CR-1, CR-4, CR-5 | complete |
| Move shared range-only PMTiles loading into this feature | `ui`, `backend-dev` | CR-1, CR-5 | complete |
| Validate shared actions, readiness and range loading before restacking the editor | `backend-validation`, `ui-validation` | CR-1, CR-4, CR-5 | complete locally |

## Delivery

Keep #200 based on main now that #183 is merged. Versioned editing remains in
the separate #201 branch. Compare actual production/test/diff sizes with the
original +8,705 lines; reduction must come
from removing unnecessary architecture and redundant scaffolding, not weakened
feature coverage. Run targeted native/API/Node regressions and the UI build.

Restacked onto refreshed #183 on 2026-09-13. Preserve the original merge's
footprint-namespace guard and artifact-route fixtures. The base now carries both
the updated GitHub Actions pins and the maintained imagery runtime/ACR build
fix, so the lower stack no longer builds the expired Debian image. Common
prediction-results behavior is unchanged.

## Review follow-up: 2026-09-18

Document the programmatic worker's result settings in `run_workflow.py`,
including the caller-supplied task ID and output-location responsibility.
Remove the standalone configuration README and manual-run instructions.
State the design and exclusions directly rather than referring to an
unrelated prototype PR.

Resolve a GeoPackage's URL and safe filename from the same model snapshot.
This removes one metadata read and a duplicate revision check per download,
without changing HTTP parameters, ownership checks, or cache/range behavior.
The regression covers a newer output appearing between the former two reads.

Validation: 19 targeted processor/API tests and 22 workflow tests passed.
Changed Python files pass flake8. Repository-wide UI lint still reports 165
errors and 8 warnings; no frontend files were changed in this follow-up.

The subsequent design simplification keeps the upper PR's threshold,
classification, version-download, and optional provenance interfaces intact.
Move its common readiness and HTTP-range groundwork down into this PR, then
retain its edited-source behavior at those same extension points. Leave the
prediction/GeoPackage writer refactor out of this work.

The dependency audit confirms production editor use of `supportsThreshold`
and version-aware downloads/reports. Default-threshold fields/constants and
`classifyAll` are also retained for the upper PR's existing fixtures and tests;
its editor initializes from the selected result's `threshold` and
`unknownThreshold`. Optional fingerprint plumbing remains unchanged.

Local simplification coverage: 83 readiness/artifact/blob tests, 23 adjacent
loading/statistics tests, and 154 targeted UI tests passed. The production UI
build and scoped UI lint passed. Full UI lint still reports the existing 165
errors and 8 warnings. No deployed range verification or service/data changes
were performed.
