# Third-Party Notices

This document contains third-party software notices and information for HASTE (High-speed Assessment and Satellite Tracking for Emergencies).

## Dependencies

This software includes third-party packages and libraries. The complete list of dependencies and their licenses can be found in the following files:

### Python Dependencies
- `api/hastefuncapi/requirements.txt`
- `api/hastefuncqueues/requirements.txt`
- `api/titilerfuncapi/requirements.txt`
- `docker/imageryprep/requirements.txt`
- `docker/training/env/env.yml`
- `hastelib/pyproject.toml`
- `env.yml`

### Node.js Dependencies
- `package.json`
- `ui/package.json`

## Major Third-Party Components

### GDAL (Geospatial Data Abstraction Library)
- **License**: MIT/X License
- **Source**: https://gdal.org/
- **Usage**: Geospatial data processing and format conversion

### HASTE GDAL Runtime (`haste-gdal-runtime`)

HASTE builds and redistributes a shared native GDAL runtime from the pinned
sources in `native/gdal-runtime/sources.lock`. Each runtime release also
ships the license and NOTICE texts extracted from these sources
(`licenses/<component>/`) plus an SBOM; see `native/gdal-runtime/`.

| Component | Version | License |
|---|---|---|
| GDAL (includes bundled libtiff, libgeotiff, libpng and json-c) | 3.13.3 | MIT/X and bundled third-party licenses (https://gdal.org/en/stable/copyright.html) |
| PROJ | 9.8.1 | MIT |
| SQLite | 3.53.4 | Public Domain (https://www.sqlite.org/copyright.html) |
| curl | 8.22.0 | curl License |
| OpenSSL | 3.5.9 | Apache-2.0 |
| zlib | 1.3.2 | Zlib; HASTE applies the upstream fix for CVE-2026-85091 (`native/gdal-runtime/patches/`) |
| libdeflate | 1.26 | MIT |
| Zstandard | 1.5.7 | BSD-3-Clause (the project is dual-licensed with GPL-2.0; HASTE uses it under BSD) |
| libjpeg-turbo | 3.1.4.1 | BSD-3-Clause, IJG and Zlib |

The Python bindings built against this runtime are:

| Package | Version | License |
|---|---|---|
| GDAL Python bindings (`osgeo`) | 3.13.3 | MIT/X |
| rasterio | 1.4.4 | BSD-3-Clause |
| fiona | 1.10.1 | BSD-3-Clause |
| pyogrio | 0.13.0 | MIT |
| pyproj | 3.7.2 | MIT |

System libraries that `auditwheel` bundles into the wheels (for example the C++ runtime) keep their own licenses, which are recorded in the runtime SBOM and license bundle.

### React
- **License**: MIT License
- **Source**: https://reactjs.org/
- **Usage**: User interface framework

### Azure SDKs
- **License**: MIT License
- **Source**: https://github.com/Azure/azure-sdk-for-python
- **Usage**: Azure cloud services integration

### FastAPI
- **License**: MIT License
- **Source**: https://fastapi.tiangolo.com/
- **Usage**: API framework

### NumPy
- **License**: BSD License
- **Source**: https://numpy.org/
- **Usage**: Numerical computing

### Pandas
- **License**: BSD License
- **Source**: https://pandas.pydata.org/
- **Usage**: Data manipulation and analysis

### Rasterio
- **License**: BSD License
- **Source**: https://rasterio.readthedocs.io/
- **Usage**: Geospatial raster data I/O

## Build / Development Tooling (Not Redistributed)

The following weak-copyleft (LGPL / MPL-2.0) packages appear in the maintainer-side build/development conda environments (`env.yml`, `env_build.yml`) as transitive dependencies of build tools (`hatch`, `azure-cli`, `fabric`, `black`). They are **not redistributed as part of the published HASTE package** — consumers of HASTE do not receive these packages from this project. They are listed here for transparency only.

| Package | License | Pulled in by |
|---|---|---|
| `paramiko` | LGPL-2.1 | `hatch` → `azure-cli` |
| `chardet` | LGPL-2.1-or-later | `azure-cli` |
| `PyGithub` | LGPL | `hatch` / `azure-cli` |
| `scp` | LGPL-2.1-or-later | `azure-cli` → `fabric` |
| `pathspec` | MPL-2.0 | `black` / `hatch` |

These packages are imported and used unmodified at build/development time. No source modification, vendoring, or static linking is performed.

## Proprietary Components (Non-OSS, Redistribution Permitted)

The following Microsoft components are **not open-source licensed** but are redistributed in HASTE under the terms of their respective licenses. Consumers integrating HASTE should review these license terms separately from the project's MIT license.

### Azure Maps Web SDK
- **Package**: `azure-maps-control` (transitive, via `azure-maps-drawing-tools`)
- **License**: Microsoft Azure Maps Web SDK End User License Agreement (proprietary)
- **License Terms**: https://azuremapscdn.azureedge.net/sdk-licenses/atlas.min.LICENSE.txt
- **Source**: https://learn.microsoft.com/en-us/azure/azure-maps/how-to-use-map-control
- **Usage**: Interactive map rendering and geospatial visualization in the UI

### Azure Maps Drawing Tools
- **Package**: `azure-maps-drawing-tools` (direct dependency)
- **License**: Microsoft Software License Terms (proprietary)
- **License Terms**: https://azuremapscdn.azureedge.net/sdk-licenses/drawing/LICENSE.txt
- **Source**: https://learn.microsoft.com/en-us/azure/azure-maps/set-drawing-options
- **Usage**: Map drawing and shape-editing controls in the UI

Use of these components requires an Azure Maps account and is subject to Azure service terms.

## Additional Notices

This software may include additional third-party software components. For a complete and up-to-date list of all dependencies and their licenses, please refer to the package manifest files listed above.

If you believe that any third-party software has been included in this project without proper attribution or in violation of its license terms, please contact the maintainers at the repository.

## License Compliance

All third-party software included in this project is used in compliance with their respective licenses. Users of this software are responsible for ensuring their use complies with all applicable license terms.
