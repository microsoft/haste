# TiTiler Tile Server API

The `titilerfuncapi` is a [TiTiler](https://developmentseed.org/titiler/)-based geospatial tile server deployed as an Azure Function. It serves Cloud Optimized GeoTIFF (COG) imagery tiles for the HASTE visualization interface.

## Endpoints

### Health Check

- **GET** `/healthz` — Returns health status

### Landing Page

- **GET** `/` — TiTiler landing page with available endpoints

### Tile Routers

The server includes the standard TiTiler routers:

| Prefix | Description |
|--------|-------------|
| `/cog` | Cloud Optimized GeoTIFF endpoints (tiles, metadata, statistics, preview) |
| `/stac` | SpatioTemporal Asset Catalog endpoints |
| `/mosaicjson` | MosaicJSON mosaic endpoints |
| `/tms` | TileMatrixSet metadata |

## Configuration

Settings are managed via the `ApiSettings` class and environment variables. The server includes middleware for:

- **CORS** — Cross-origin requests from the UI
- **Compression** — Response compression
- **Cache Control** — Tile caching headers
- **Query String Normalization** — Consistent parameter handling

## Deployment

The tile server can be deployed as:

- **Azure Function** — Using the `titilerfuncapi/` function app with `AsgiMiddleware`
- **Docker container** — Using `docker/titiler/Dockerfile` (standalone uvicorn on port 8000)

## Dependencies

- `azure-functions`
- `titiler.application==0.21.1`
