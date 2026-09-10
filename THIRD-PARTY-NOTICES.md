# Third-Party Notices

This document contains third-party software notices and information for HASTE (High-speed Assessment and Satellite Tracking for Emergencies).

## Contents

- [Dependencies](#dependencies)
- [Major Third-Party Components](#major-third-party-components)
- [Optional DINOv3 Model Assets (Not Bundled)](#optional-dinov3-model-assets-not-bundled)
- [Build / Development Tooling](#build--development-tooling-not-redistributed)
- [Proprietary Components](#proprietary-components-non-oss-redistribution-permitted)
- [Additional Notices](#additional-notices)
- [License Compliance](#license-compliance)

## Dependencies

This software includes third-party packages and libraries. The complete list of dependencies and their licenses can be found in the following files:

### Python Dependencies
- `api/hastefuncapi/requirements.txt`
- `api/hastefuncqueues/requirements.txt`
- `api/titilerfuncapi/requirements.txt`
- `docker/imageryprep/requirements.txt`
- `docker/training/env/env.yml`
- `docker/transformerinference/requirements.txt`
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

### Transformers (DINOv3 Backbone Implementation)
- **Package**: `transformers`
- **License**: Apache License 2.0
- **License Terms**: https://github.com/huggingface/transformers/blob/v5.5.4/LICENSE
- **Source**: https://github.com/huggingface/transformers
- **Usage**: Constructs the DINOv3 backbone from separately supplied configuration and weights in the optional transformer inference image.

The DINOv3 implementation in Transformers carries the notice:
Copyright 2025 Meta AI and The HuggingFace Inc. team. All rights reserved.

### Building Damage Assessment Adapter Code
- **License**: MIT License
- **Copyright**: Copyright (c) Microsoft Corporation.
- **Source**: https://github.com/microsoft/building-damage-assessment/tree/4d0d1925dc3a5a63566f047102f8dd474dbbcf80
- **Usage**: DINOv3 UPerNet architecture and raster inference code adapted for HASTE.

## Optional DINOv3 Model Assets (Not Bundled)

HASTE includes integration code for separately supplied DINOv3 models, not a
bundled DINOv3 model. Checkpoint weights and associated backbone configuration
assets are obtained and imported separately into an operator's storage; they
are not included in the HASTE source repository.

The custom xView2 checkpoint used during local development was imported only
to exercise this integration. Its packaging, hosting, and distribution are
separate from HASTE, and deploying HASTE does not automatically install it.
Local test assets under `localtmp/` are excluded from Git.

DINOv3 model assets and derivatives remain subject to the separate
[Meta DINOv3 License](https://github.com/facebookresearch/dinov3/blob/ffb4bb89c6558ca3244655c25a3955d01788b732/LICENSE.md),
including its use restrictions and redistribution requirements. Anyone
distributing those materials or derivatives separately must comply with that
agreement, including providing a copy with the distributed materials.

Neither HASTE's MIT license nor the Transformers implementation's Apache-2.0
license relicenses separately supplied DINOv3 model assets.

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
