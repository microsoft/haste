# Impact: Common Prediction Results

## Risks

| Risk | Mitigation |
|---|---|
| Attribute rows color unrelated footprints | Explicit identity/count validation and producer regression coverage |
| Regenerated predictions retain stale attributes | Publish matching artifact state and cover repeat saves/inference |
| Larger synchronous interactive saves | Reuse the prediction GeoPackage already being written; no tiling in HTTP |
| Older layers lack artifacts | Show explicit missing-artifact guidance; retain raw downloads |
| PMTiles handler collision | One protocol instance shared by both viewers |
| Saved project disruption during development | Do not restart or reseed the user's running stack |

## Dependencies

#183 owns layer footprint tiles. Standard sidecar generation must ship with
the updated training image, API, and core library. The editing feature depends
on this shared results contract; it does not add another preparation service.
