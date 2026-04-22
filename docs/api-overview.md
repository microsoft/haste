# API Overview

The HASTE API provides 28 HTTP endpoints and 6 queue-triggered functions for managing disaster assessment projects, processing satellite imagery, and running AI models for damage assessment. A separate TiTiler-based tile server handles geospatial imagery visualization.

## Architecture

The API layer consists of three Azure Functions apps:

- **`hastefuncapi`** — 28 HTTP-triggered endpoints for CRUD operations (projects, layers, models, labels, users, admin, catalog)
- **`hastefuncqueues`** — 6 queue-triggered functions for async processing (imagery, training, inference, stats, artifacts, error handling)
- **`titilerfuncapi`** — TiTiler tile server for Cloud Optimized GeoTIFF serving

All apps share the `haste` core library for models, processors, and storage backends.

## Authentication

All HTTP API endpoints use `func.AuthLevel.FUNCTION` authentication:

- **Azure Functions keys** for development and testing
- **Azure AD integration** (via MSAL in the React UI) for production deployments

## Base URLs

- **Development**: `http://localhost:7071/api/`
- **Production**: `https://your-function-app.azurewebsites.net/api/`

## Common Response Formats

### Success Response

```javascript
{
  "data": {},
  "status": "success",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Error Response

```json
{
  "error": "Error description",
  "details": "Additional error details if available",
  "status": "error",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Rate Limits

API calls are subject to:

- **Azure Functions consumption plan limits**
- **CosmosDB request unit (RU) quotas**
- **Blob storage bandwidth limits**

## HTTP Status Codes

- **200 OK** - Request successful
- **201 Created** - Resource created successfully
- **400 Bad Request** - Invalid request data
- **401 Unauthorized** - Authentication required
- **404 Not Found** - Resource not found
- **500 Internal Server Error** - Server error
