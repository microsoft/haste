# Impact Analysis: [Feature Title]

## Scope of Change

### HASTE Components Affected

| Component | Path | Type of Change | Severity |
|---|---|---|---|
| Core library | `hastelib/src/hastegeo/...` | new / modified / deprecated | low / medium / high |
| REST API | `api/hastefuncapi/function_app.py` | new / modified | low / medium / high |
| Queue workers | `api/hastefuncqueues/function_app.py` | new / modified | low / medium / high |
| Tile server | `api/titilerfuncapi/` | new / modified | low / medium / high |
| React UI | `ui/src/Components/...` | new / modified | low / medium / high |
| Docker config | `docker/...` | modified | low / medium / high |
| CI/CD | `.github/workflows/...` | modified | low / medium / high |

> Remove rows for components not affected.

## Azure Service Impact

| Service | Change | New Cost Impact |
|---|---|---|
| Cosmos DB | New container / modified schema / increased RU | |
| Blob Storage | New containers / changed access patterns | |
| Data Lake | New filesystem / path changes | |
| Azure Batch | New pool config / GPU SKU change | |
| Queue Storage | New queues / changed message format | |
| Azure Functions | New functions / changed consumption | |
| Static Web Apps | Config changes / new API routes | |

> Remove rows for services not affected.

## Dependency Analysis

### Upstream Dependencies (things this feature needs)

| Dependency | Type | Status | Risk if Unavailable |
|---|---|---|---|
| `hastegeo` core module | library | available | |
| Imagery provider API | external API | | |
| Azure Batch GPU pool | infra | | |
| MSAL auth tokens | auth | available | |

### Downstream Impact (things affected by this feature)

| Consumer | How Affected | Breaking? | Migration Needed? |
|---|---|---|---|
| `hastefuncapi` callers | | yes / no | yes / no |
| React UI components | | yes / no | yes / no |
| Docker Compose stack | | yes / no | yes / no |
| Existing Cosmos documents | | yes / no | yes / no |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Cosmos schema change breaks existing projects | | | | |
| GPU pool unavailability delays processing | | | | |
| Large imagery files exceed Blob timeout | | | | |

## Performance Impact

- **API latency:** Expected change to `hastefuncapi` response times
- **Queue throughput:** Expected change to `hastefuncqueues` processing rate
- **Tile serving:** Impact on `titilerfuncapi` tile generation
- **Batch compute:** GPU pool utilization changes
- **Storage I/O:** Blob/Data Lake read/write patterns

## Security Impact

- [ ] New API endpoints exposed? (check `func.AuthLevel`)
- [ ] New data classification handled? (satellite imagery, PII)
- [ ] MSAL/Entra ID auth changes?
- [ ] New secrets or connection strings required?
- [ ] CORS configuration changes in SWA?
- [ ] New federated credentials needed? (see `fed-cred-*.json`)

## Compliance & Data Impact

- [ ] Geospatial data sovereignty concerns?
- [ ] Partner data sharing agreements affected?
- [ ] New data retention requirements?
- [ ] Audit logging for new operations?
- [ ] Component Governance scan implications? (new Python/npm deps)

## Rollback Assessment

- **Reversibility:** fully reversible / partially reversible / irreversible
- **Cosmos data:** Can documents be migrated back? [describe]
- **Blob data:** Can artifacts be cleaned up? [describe]
- **API:** Are endpoints backward-compatible?
- **Estimated rollback time:** [duration]
