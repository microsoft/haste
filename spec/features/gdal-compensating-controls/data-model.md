# Data Model: GDAL Deferral Compensating Controls

## Summary

**No data-model changes.** This feature adds process-level hardening and
ingestion-boundary checks only. It introduces no new Cosmos DB documents,
Blob/Data Lake layouts, PostgreSQL tables, or message schemas, and does not
alter any existing persisted shape.

## Cosmos DB

No changes.

## Blob Storage / Data Lake

No changes. Uploaded/downloaded files retain their existing paths and
formats; the only difference is that oversized or wrong-type inputs are
rejected before they are persisted/parsed.

## PostgreSQL

No changes.

## Configuration (not persisted data, listed for completeness)

| Key | Type | Default |
|---|---|---|
| `HASTE_MAX_UPLOAD_BYTES` | int | 5 GiB |
| `HASTE_MAX_IMAGERY_DOWNLOAD_BYTES` | int | 8 GiB |
| `GDAL_SKIP` | str | `HDF4 HDF4Image HDF5 HDF5Image netCDF` |
