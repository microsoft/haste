---
name: deterministic-scripts
description: "Deterministic script execution skill for HASTE. Execute scripts instead of free-form LLM behavior for consistent, repeatable operations. Use when: 'run preprocessing', 'convert format', 'parse metadata', 'generate tiles', 'build wheel', 'deploy functions'. Prevents hallucinated scripts."
source: "HASTE operational scripts, build system"
domain: "operations"
level: "foundational"
agents: ["backend-dev", "gis", "backend-validation"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Deterministic Script Execution

## Overview

HASTE has established scripts and commands for common operations. Agents must use these exact commands instead of generating free-form alternatives. This prevents hallucinated scripts, ensures consistency, and makes operations repeatable.

## Key Concepts

### Why Deterministic Scripts Matter
- LLMs can "helpfully" generate plausible-looking but incorrect commands
- HASTE has specific build tooling (hatch, conda) that must be used correctly
- Azure Functions deployment has specific prerequisites and ordering
- Geospatial processing requires exact GDAL/rasterio invocations

## Patterns & Techniques

### Build & Package Operations

| Operation | Exact Command | Notes |
|-----------|--------------|-------|
| Build core wheel | `cd hastelib && hatch build -t wheel` | Auto-increments version, copies to func apps |
| Run Python tests | `cd hastelib && hatch run test:pytest` | Uses conda env with GDAL |
| Build UI | `cd ui && npm run build` | Production build via Vite |
| Lint UI | `cd ui && npm run lint` | ESLint with React rules |
| Install UI deps | `cd ui && npm install` | Uses package-lock.json |
| Create conda env | `conda env create -f env.yml` | Full env with GDAL and dependencies |
| Update conda env | `conda env update -f env.yml` | Preserves existing packages |
| Install hastelib editable | `pip install -e hastelib/` | For local development hot-reload |

### Local Development

| Operation | Exact Command | Notes |
|-----------|--------------|-------|
| Start API locally | `cd api/hastefuncapi && func host start` | Requires `.venv` or conda env |
| Start UI locally | `cd ui && swa start --app-devserver-url http://localhost:5173 --run 'npm run dev'` | SWA CLI with Vite dev server |
| Start Azurite | `azurite --silent --location ./data --debug ./data/debug.log` | Local Azure Storage emulator |
| Start Docker stack | `docker-compose -f docker/docker-compose.yml up` | Full local stack |

### Deployment

| Operation | Exact Command | Notes |
|-----------|--------------|-------|
| Deploy Azure Function | `func azure functionapp publish <NAME> --subscription <SUB> --tenant <TENANT>` | After `hatch build` |
| Deploy SWA | `cd ui && swa deploy --app-location ./dist --app-name <NAME>` | After `npm run build` |
| Build Docker images | `./build_and_push_images.sh` | Builds training + imagery prep images |

### Imagery Processing

| Operation | Approach | Notes |
|-----------|----------|-------|
| COG generation | Use rasterio with `COG` driver profile | Never use raw GDAL CLI unless wrapping in Python |
| Tile generation | Through `ImageryPreProcessor` | Not manual gdal2tiles |
| Reprojection | `rasterio.warp.reproject()` | Always specify `src_crs` and `dst_crs` |
| Format conversion | Through provider-specific adapter | Not generic `gdal_translate` |

## Decision Framework

| Situation | Do This | NOT This |
|-----------|---------|----------|
| Need to run tests | `hatch run test:pytest` | `pytest` (wrong env) |
| Need to build wheel | `hatch build -t wheel` | `python setup.py bdist_wheel` |
| Need to start API | `func host start` | `python function_app.py` |
| Need Azure storage locally | `azurite` | Custom mock storage |
| Need to process imagery | Use `ImageryPreProcessor` | Write new GDAL script |
| Need to deploy | `func azure functionapp publish` | Manual zip deployment |

## Common Pitfalls

- **Inventing new build commands** — Use the established commands above
- **Running pytest directly** — Use `hatch run test:pytest` to get the correct conda env
- **Starting the UI with `npm start`** — HASTE uses `swa start` with Vite dev server
- **Using `python setup.py`** — HASTE uses hatch/hatchling, not setuptools
- **Generating GDAL scripts from scratch** — Use existing processor methods
