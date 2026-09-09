# Imagery worker MCR base recovery

**Status:** in-progress

Replace the imagery worker's Debian 11 Functions base after its security
repository metadata expired. Preserve Python 3.11, existing native-library pins,
the non-root task entrypoint, and GPU-worker behavior.

Maintain this shared fix upstream and synchronize it into downstream forks.

The initial candidate is the digest-pinned MCR Azure ML minimal Python 3.11
image on Ubuntu 22.04. Its curated environment is marked Preview; a successful
local experiment is compatibility evidence, not production approval.

## Table of contents

- [Acceptance criteria](#acceptance-criteria)
- [Local results](#local-results)
- [Agent assignment map](#agent-assignment-map)
- [Documents](#documents)

## Acceptance criteria

- Build the actual imagery Dockerfile without disabling repository validation.
- Keep Python 3.11 and install the existing GDAL 3.9.2 wheel and dependency pins.
- Exercise native raster creation, mosaicking, reprojection, RGB COG conversion,
  preview generation, and vector I/O, not only imports or mocked tests.
- Run the existing targeted imagery and workflow tests inside the image.
- Preserve non-root operation, relative task-directory behavior, and GDAL
  driver restrictions.
- Leave the CUDA training image, Azure resources, and deployments unchanged.
- Keep CI's Python-version guard compatible with the actual MCR reference.

## Local results

The candidate built successfully on Linux AMD64 using an approved internal Python
feed supplied as a temporary build secret. Python 3.11.16, GDAL 3.9.2,
rasterio 1.3.11, and OpenCV 4.10.0 load in the isolated worker environment.
The original dependency pins are unchanged and `pip check` passes.

The non-root image entrypoint passed 31 tests, including six real native raster,
COG, reprojection, JPEG, vector, and driver-restriction tests. Network access was
disabled for runtime tests. The build-time feed configuration was not retained.
GitHub Actions/ACR compatibility and an authenticated Batch run remain unverified;
this local image has not been pushed or deployed.

The same runtime passed the 31 tests with this upstream checkout mounted
read-only over the application source. Its 23 dependency-guard tests also passed;
the existing AML-backend tests and requirements were preserved during transfer.

## Agent assignment map

| Story | Implementing agent | Validating agent |
|---|---|---|
| Recover the supported-OS imagery build and CI guard | `backend-dev` | `backend-validation` |
| Verify native imagery compatibility | `gis` | `backend-validation` |

## Documents

- [Design and validation](design.md)
- [Existing GDAL controls](../gdal-compensating-controls/design.md)
