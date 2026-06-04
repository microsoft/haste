# Data Model: [Feature Title]

## Cosmos DB Changes

### New Containers

| Container | Partition Key | Description |
|---|---|---|
| | | |

### Modified Containers

| Container | Change | Migration Needed? |
|---|---|---|
| | | yes / no |

### New Document Schema

**Container:** `[container-name]`
**Partition key:** `[key]`

```json
{
  "id": "uuid",
  "partitionKey": "string",
  "type": "string — document type discriminator",
  "field1": "type — description",
  "field2": "type — description",
  "created_at": "ISO 8601 datetime",
  "updated_at": "ISO 8601 datetime"
}
```

**RU estimate:** [read/write RU cost per operation]

### Modified Document Schema

| Container | Field | Before | After | Notes |
|---|---|---|---|---|
| | | | | |

---

## Blob Storage Changes

### New Containers

| Container | Access Level | Naming Convention | Content Type |
|---|---|---|---|
| | private | `{project_id}/{layer_id}/...` | GeoTIFF / JSON / ... |

### Modified Containers

| Container | Change | Description |
|---|---|---|
| | | |

### Blob Path Conventions

```
{container}/
  {project_id}/
    {layer_id}/
      {artifact_type}/
        {filename}
```

---

## Data Lake Changes

### New Filesystems / Paths

| Filesystem | Path Pattern | Data Format | Description |
|---|---|---|---|
| | | Parquet / CSV / COG | |

---

## Queue Storage Changes

### New Queues

| Queue Name | Message Schema | Producer | Consumer |
|---|---|---|---|
| | See [design.md](design.md) | `hastefuncapi` | `hastefuncqueues` |

---

## Azure Batch Changes

### Pool Configuration

| Setting | Value | Notes |
|---|---|---|
| VM SKU | | e.g. Standard_NC6s_v3 (GPU) |
| Pool size | | auto-scale formula if applicable |
| Container image | | `docker/training/` or `docker/imageryprep/` |

---

## Data Flow

### Write Path

```
UI → hastefuncapi → Cosmos DB (metadata)
                  → Queue Storage (job message)
                  → hastefuncqueues → hastegeo processor
                                    → Blob Storage (artifacts)
                                    → Data Lake (large datasets)
                                    → Azure Batch (GPU compute)
```

### Read Path

```
UI → hastefuncapi → Cosmos DB (metadata)
                  → Blob Storage (artifacts, direct SAS URL)
UI → titilerfuncapi → Blob Storage (COG tiles)
```

## Migration Plan

### Forward Migration

1. Deploy new Cosmos container(s) or update schema
2. Backfill existing documents if needed
3. Deploy API changes
4. Deploy UI changes

### Backward Migration

1. Revert API to previous version
2. Cosmos documents: [describe backward compatibility]
3. Blob artifacts: [describe cleanup]

## Data Volume Estimates

| Entity / Container | Initial Size | Growth Rate | Retention |
|---|---|---|---|
| | | /day, /month | |

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| | In-memory (API) / Browser / CDN | | |
