# Plan: Common Prediction Results

## Implementation

| Task | Agent | Stories | Status |
|---|---|---|---|
| Remove shadow metadata/lifecycle machinery; retain direct Model result writes | `backend-dev` | CR-2 to CR-5 | complete |
| Consolidate raw attribute/GeoPackage helpers without weakening identity checks | `gis` | CR-2, CR-3 | complete |
| Preserve the shared viewer and protected downloads | `ui` | CR-1, CR-4, CR-5 | complete |
| Validate paired writes, clear/failure/freshness, ownership, and existing inference wiring | `backend-validation` | CR-2 to CR-5 | complete |
| Confirm unchanged viewer contracts, cancellation and download behavior | `ui-validation` | CR-1, CR-4, CR-5 | complete |
| Clarify standalone revision IDs and make the specification self-contained | `backend-dev` | CR-2, CR-3 | complete |
| Resolve protected download URLs and filenames with one model read | `backend-dev` | CR-5 | complete |
| Verify single-read downloads, ownership, stale revisions, and safe filenames | `backend-validation` | CR-5 | complete |

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

Define the standalone revision as an output-pair ID, show UUIDv4 generation,
and explain the managed task-ID equivalent. State the design and exclusions
directly rather than referring to an unrelated prototype PR.

Resolve a GeoPackage's URL and safe filename from the same model snapshot.
This removes one metadata read and a duplicate revision check per download,
without changing HTTP parameters, ownership checks, or cache/range behavior.
The regression covers a newer output appearing between the former two reads.

Validation: 19 targeted processor/API tests and 22 workflow tests passed.
Changed Python files pass flake8. Repository-wide UI lint still reports 165
errors and 8 warnings; no frontend files were changed in this follow-up.
