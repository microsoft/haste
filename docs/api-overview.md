# API Overview

The HASTE API provides **41 HTTP endpoints** and **6 queue-triggered workers** (plus a
poison-queue handler) for managing disaster assessment projects, processing satellite
imagery, and running AI models for damage assessment. A separate TiTiler-based tile server
handles geospatial imagery visualization.

## Architecture

The API layer consists of three Azure Functions apps:

- **`hastefuncapi`** — 41 HTTP-triggered endpoints (projects, image layers, models, labels
  and validation, building features, users and admin, model catalog, plus dashboard/stats,
  visualizer, chunked upload, and Azure Maps token)
- **`hastefuncqueues`** — 6 queue-triggered workers plus a poison-queue handler for async
  processing (imagery, training, embedding, inference, stats, and artifact zipping)
- **`titilerfuncapi`** — a TiTiler `0.21.1` tile server for Cloud Optimized GeoTIFF serving

All apps share the `hastegeo` core library for models, processors, and storage backends.

## Authentication

Authentication is **environment-dependent**:

- **Local / development** (`DEVELOPMENT_MODE=true`) — endpoints are anonymous
  (`func.AuthLevel.ANONYMOUS`) for convenient local testing.
- **Production** (`DEVELOPMENT_MODE=false`, the default) — endpoints require a Function key
  (`func.AuthLevel.FUNCTION`). Azure API Management fronts the app and injects the Function
  host key into its backends; the React UI authenticates users via Entra ID (MSAL) at the
  Static Web App.

Admin endpoints additionally enforce an `administrators` role decoded from the SWA-provided
`x-ms-client-principal` header, and the Model Catalog endpoints are always `FUNCTION`.

## Base URLs

- **Local** — the UI is served by the SWA CLI at `http://localhost:4280`; API calls go
  through the nginx `api-proxy` at `http://localhost:7071/api/`.
- **Production** — the API is fronted by Azure API Management, and the Static Web App
  proxies `/api/*` to it.

## Response Formats

Responses are shaped per endpoint — **there is no global response envelope**. Successful
reads return the resource directly, sometimes under a named key:

```json
{ "projects": [], "project_count": 0, "layer_count": 0, "model_count": 0 }
```

Errors return an appropriate HTTP status code with either a plain-text message or a JSON
body such as:

```json
{ "error": "Project not found." }
```

Some write endpoints (e.g. the Model Catalog) return a small status wrapper:

```json
{ "success": true, "message": "…", "catalogModel": {} }
```

## Rate Limits

API throughput is bounded by the underlying platform:

- **Azure Functions** plan limits (Flex Consumption)
- **Cosmos DB** request-unit (RU) quotas, when the Cosmos metadata backend is used
- **API Management** policies in front of the API
- **Blob storage** bandwidth

## HTTP Status Codes

- **200 OK** — request successful
- **201 Created** — resource created successfully
- **400 Bad Request** — invalid request data
- **401 Unauthorized** — authentication required
- **403 Forbidden** — authenticated but missing the required role
- **404 Not Found** — resource not found
- **500 Internal Server Error** — server error
