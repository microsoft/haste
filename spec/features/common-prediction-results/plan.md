# Plan: Common Prediction Results

## Implementation

| Task | Agent | Stories | Status |
|---|---|---|---|
| Remove shadow metadata/lifecycle machinery; retain direct Model result writes | `backend-dev` | CR-2 to CR-5 | complete |
| Consolidate raw attribute/GeoPackage helpers without weakening identity checks | `gis` | CR-2, CR-3 | complete |
| Preserve the shared viewer and protected downloads | `ui` | CR-1, CR-4, CR-5 | complete |
| Validate paired writes, clear/failure/freshness, ownership, and existing inference wiring | `backend-validation` | CR-2 to CR-5 | complete |
| Confirm unchanged viewer contracts, cancellation and download behavior | `ui-validation` | CR-1, CR-4, CR-5 | complete |

## Delivery

Keep #200 based on #183 and restack #201 after simplification. Compare actual
production/test/diff sizes with the original +8,705 lines; reduction must come
from removing unnecessary architecture and redundant scaffolding, not weakened
feature coverage. Run targeted native/API/Node regressions and the UI build.
