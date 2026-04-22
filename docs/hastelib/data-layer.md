# Data Layer

The `haste.core.data_layer` package provides a multi-backend storage abstraction for HASTE metadata and file storage. The unified data layer delegates to backend-specific implementations based on configuration.

## Supported Backends

| Backend | Class | Use Case |
|---------|-------|----------|
| Local filesystem | `LocalFileSystemDataLayer` | Local development |
| Azure Blob Storage | `AzureBlobStorageDataLayer` | Cloud file storage |
| Azure CosmosDB | `AzureCosmosDbDataLayer` | Cloud document storage |
| Azure Data Lake | `AzureDataLakeDataLayer` | Cloud hierarchical storage |
| PostgreSQL | `AzurePostgresqlDataLayer` | Relational database storage |

## Unified Data Layer (`haste.core.data_layer.unified`)

Factory wrapper that instantiates the correct backend based on the `StorageType` configuration.

```{eval-rst}
.. automodule:: haste.core.data_layer.unified
   :members:
   :undoc-members:
   :show-inheritance:
```

## Abstract Base (`haste.core.data_layer.abstract_data_layer`)

Defines the interface all data layer implementations must follow.

**Abstract methods:** `save()`, `save_chunk()`, `finalize_save()`, `update()`, `load()`, `load_all()`, `delete()`

```{eval-rst}
.. automodule:: haste.core.data_layer.abstract_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```

## Local Filesystem (`haste.core.data_layer.local_file_system_data_layer`)

```{eval-rst}
.. automodule:: haste.core.data_layer.local_file_system_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```

## Azure Blob Storage (`haste.core.data_layer.azure_blob_storage_data_layer`)

```{eval-rst}
.. automodule:: haste.core.data_layer.azure_blob_storage_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```

## Azure CosmosDB (`haste.core.data_layer.azure_cosmos_db_data_layer`)

```{eval-rst}
.. automodule:: haste.core.data_layer.azure_cosmos_db_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```

## Azure Data Lake (`haste.core.data_layer.azure_data_lake_data_layer`)

```{eval-rst}
.. automodule:: haste.core.data_layer.azure_data_lake_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```

## PostgreSQL (`haste.core.data_layer.azure_postgresql_data_layer`)

```{eval-rst}
.. automodule:: haste.core.data_layer.azure_postgresql_data_layer
   :members:
   :undoc-members:
   :show-inheritance:
```
