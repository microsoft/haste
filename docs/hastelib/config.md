# Configuration

The `haste.core.config` module provides environment-aware configuration for all HASTE services. It reads environment variables to configure storage backends, queue names, paths, and credentials.

## Key Classes

- **`Config`** — Main configuration class with static methods for accessing environment settings
- **`StorageType`** (Enum) — Storage backend types: `LOCAL`, `BLOB`, `COSMOS`, `DATALAKE`, `POSTGRES`
- **`ArtifactTypes`** (Enum) — Artifact naming templates for pre/post event imagery, model artifacts, etc.
- **`InviteConfig`** (NamedTuple) — Configuration for the user invitation system

## Environment Variables

The `Config` class reads from these key environment variables (see `local.settings.example.jsonc`):

| Variable | Description |
|----------|-------------|
| `DATA_PATH` | Base path for local data storage |
| `TEMP_DATA_PATH` | Temporary processing directory |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob/Queue Storage connection |
| `COSMOS_CONNECTION_STRING` | Azure CosmosDB connection |
| `METADATA_STORAGE_TYPE` | Backend for metadata (`blob`, `localfilesystem`, `cosmos`, etc.) |
| `IMAGERY_STORAGE_TYPE` | Backend for imagery files |
| `ARTIFACT_STORAGE_TYPE` | Backend for model artifacts |
| `IMAGE_QUEUE`, `TRAIN_QUEUE`, etc. | Queue names for async processing |

```{eval-rst}
.. automodule:: haste.core.config
   :members:
   :undoc-members:
   :show-inheritance:
```
