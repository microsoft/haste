# Technical Design: [Feature Title]

## Overview

High-level technical approach in 2-3 sentences. Reference the HASTE architecture diagram in `docs/architecture.md`.

## Architecture

### Component Diagram

```
┌──────────────────┐     ┌───────────────────┐     ┌──────────────┐
│   React UI       │────▶│   hastefuncapi     │────▶│  Cosmos DB   │
│   (Fluent UI)    │     │   (Azure Func)     │     │              │
└──────────────────┘     └────────┬───────────┘     └──────────────┘
                                  │ queue msg
                         ┌────────▼───────────┐     ┌──────────────┐
                         │   hastefuncqueues   │────▶│  Blob Storage│
                         │   (Azure Func)      │     │  / Data Lake │
                         └────────┬───────────┘     └──────────────┘
                                  │
                         ┌────────▼───────────┐
                         │   hastegeo core     │
                         │   (processors/      │
                         │    runners/models)   │
                         └────────┬───────────┘
                                  │
                         ┌────────▼───────────┐
                         │   Azure Batch      │
                         │   (GPU pools)      │
                         └────────────────────┘
```

> Modify diagram to show only the flow relevant to this feature.

### New Components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| | `hastelib/src/hastegeo/...` | | Python |
| | `api/hastefuncapi/...` | | Azure Functions |
| | `ui/src/Components/...` | | React / Fluent UI |

### Modified Components

| Component | Path | Change Description |
|---|---|---|
| | | |

## API Design

### hastefuncapi Endpoints

#### `[METHOD] /api/[endpoint]`

**Auth:** `func.AuthLevel.FUNCTION`

**Request:**

```json
{
  "field": "type — description"
}
```

**Response (200):**

```json
{
  "field": "type — description"
}
```

**Error Responses:**

| Code | Condition |
|---|---|
| 400 | Invalid request body |
| 401 | Missing/invalid function key or MSAL token |
| 404 | Resource not found in Cosmos DB |
| 500 | Internal error (Batch failure, storage error) |

### Queue Messages (hastefuncqueues)

#### Queue: `[queue-name]`

**Message Schema:**

```json
{
  "project_id": "string",
  "operation": "string",
  "payload": {}
}
```

**Trigger behavior:** [describe what the queue worker does]

### Internal Interfaces (hastegeo)

| Module | Function/Class | Signature | Description |
|---|---|---|---|
| `core/models/` | | | |
| `core/processors/` | | | |
| `core/data_layer/` | | | |
| `core/runners/` | | | |

## Behavior & Logic

### Core Flow

1. User initiates action in React UI
2. UI calls `hastefuncapi` endpoint via SWA proxy (`/api/...`)
3. API validates request, writes to Cosmos DB
4. API enqueues message to Azure Queue Storage
5. `hastefuncqueues` picks up message, invokes `hastegeo` processor
6. Processor submits job to Azure Batch (if GPU needed)
7. Results written to Blob Storage / Data Lake
8. UI polls or receives update

### Edge Cases

| Case | Expected Behavior |
|---|---|
| Imagery file exceeds size limit | |
| Azure Batch pool has no available nodes | |
| Cosmos DB RU throttling | |
| Queue message processing fails | |
| Concurrent project modifications | |

### Error Handling

| Error Condition | Response | Recovery |
|---|---|---|
| Blob upload timeout | | Retry with exponential backoff |
| Batch job failure | | Dead-letter queue + admin notification |
| Cosmos conflict (409) | | Retry with etag check |

## Configuration

| Config Key | Type | Default | Where Set | Description |
|---|---|---|---|---|
| | | | `local.settings.json` / App Settings | |
| | | | `docker-compose.yml` env vars | |
| | | | `ui/.env.*` | |

## Observability

- **Logs:** Structured logging via Python `logging` in Azure Functions
- **Metrics:** Azure Monitor / Application Insights
- **Queue depth:** Monitor Azure Queue Storage metrics
- **Batch jobs:** Azure Batch job/task status monitoring
- **UI errors:** Browser console + any error tracking

## Open Questions

- [ ] Unresolved design items.
