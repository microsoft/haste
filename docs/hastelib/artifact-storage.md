# Artifact Storage

The `haste.core.artifact_storage` package provides an abstraction layer for storing and retrieving model artifacts (weights, predictions, configuration files).

## Supported Backends

| Backend | Class | Description |
|---------|-------|-------------|
| Local filesystem | `LocalFileSystemArtifactStorage` | Local development storage |
| Azure Blob Storage | `AzureBlobArtifactStorage` | Cloud storage with SAS URL generation |

## Unified Artifact Storage (`haste.core.artifact_storage.unified_artifact_storage`)

Factory wrapper that delegates to the correct backend implementation.

```{eval-rst}
.. automodule:: haste.core.artifact_storage.unified_artifact_storage
   :members:
   :undoc-members:
   :show-inheritance:
```

## Abstract Base (`haste.core.artifact_storage.abstract_artifact_storage`)

Defines the interface and shared utilities for all artifact storage implementations.

**Abstract methods:** `get_file_path()`, `get_download_url()`, `fetch_artifact()`, `store_artifact()`, `get_base_url()`

**Utility functions:** `is_json()`, `is_bytes()`, `is_yaml()`

```{eval-rst}
.. automodule:: haste.core.artifact_storage.abstract_artifact_storage
   :members:
   :undoc-members:
   :show-inheritance:
```

## Azure Blob Storage (`haste.core.artifact_storage.azure_blob_artifact_storage`)

Stores artifacts in Azure Blob Storage with SAS-token-enabled download URLs.

```{eval-rst}
.. automodule:: haste.core.artifact_storage.azure_blob_artifact_storage
   :members:
   :undoc-members:
   :show-inheritance:
```

## Local Filesystem (`haste.core.artifact_storage.local_file_system_artifact_storage`)

Stores artifacts on the local filesystem for development.

```{eval-rst}
.. automodule:: haste.core.artifact_storage.local_file_system_artifact_storage
   :members:
   :undoc-members:
   :show-inheritance:
```
