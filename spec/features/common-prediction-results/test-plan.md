# Test Plan: Common Prediction Results

## Coverage

| Surface | Required evidence |
|---|---|
| Attribute builder | Both producer schemas; ID/count agreement; CRS/row preservation; unknown and non-finite values |
| Interactive save | Eager matching sidecar; repeat prediction refresh; empty clear; upload failure; no false readiness |
| Standard inference | Sidecar emitted during inference and published by completion; unavailable output fails rather than advertises ready |
| API | Both workflow payloads; model/layer mismatch; artifact-not-found; existing authorization; reads do not enqueue |
| UI helpers | Both flavors, empty/missing states, stable identity, singleton PMTiles and cancellation |
| Results map | Both panes match; appropriate raster layers; no first-open preparation request; protected proxy downloads |

## Execution

Use the existing pytest and Node test runners with targeted selectors. Run
the UI build and lint; distinguish unchanged baseline diagnostics from new
ones. Use isolated browser fixtures for UI behavior rather than changing the
running development stack or seeding its project storage.

## Observed Evidence

The independent UI pass executed 55 passing browser cases using Chrome and
the actual Azure Maps SDK/WebGL renderer, with fixture auth, API, styles, and
rasters. It covered both workflows, both panes, revision replacement, missing
artifacts, cancellation, write errors/partial clears, dark/narrow layouts, and
comparison controls across 991/992/1100/1199/1200px. It did not exercise live
authentication or Azure basemap services.

Native GIS validation covered real GeoPackage/JSON/COG output for scored,
empty, and all-nodata fixtures. The expanded producer suite has 82 passing
cases. Backend failure-path validation remains the final publication gate.
Final backend revalidation passed 227 cases, including report authority after
clear/stale saves, mirror-write failure recovery, metadata-error classification,
model deletion/recreation, and stale-cancellation rejection. The complete UI
Node suite passed 156 cases and the production build completed. Existing
repository-wide UI lint diagnostics were compared separately; changed code
introduces none.
