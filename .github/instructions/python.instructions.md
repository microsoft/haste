---
applyTo: "**/*.py"
---

# Python Instructions

- Python 3.11+. Use type hints on all function signatures.
- Use Pydantic models for data validation — follow existing models in `hastegeo.core.models`.
- Use `Config` class from `hastegeo.core.config` for all credentials and connection strings.
- Use `Logger.get_logger()` from `hastegeo.core.utils.logs` for logging.
- Use GDAL/rasterio for geospatial file operations — never raw file I/O for imagery.
- Follow existing processor patterns in `hastegeo.core.processors` for business logic.
- Follow existing data layer patterns in `hastegeo.core.data_layer` for storage backends.
- API endpoints use `@app.route()` with `AUTH_LEVEL` — never hardcode `ANONYMOUS`.
- Use `MetadataUtils` for ID generation and timestamps.
- Pin dependency versions in `requirements.txt` files.
- Run tests with hatch: `cd hastelib && hatch run test:pytest` (from repo root).
