# Runners

The `haste.core.runners` package provides task execution backends for running compute-intensive operations (training, inference, imagery preprocessing) on remote infrastructure.

## Supported Backends

| Backend | Class | Description |
|---------|-------|-------------|
| Azure Batch | `AzureBatchRunner` | GPU-enabled task execution via Azure Batch pools |

## Unified Runner (`haste.core.runners.unified_runner`)

Factory wrapper that instantiates the correct runner based on configuration.

```{eval-rst}
.. automodule:: haste.core.runners.unified_runner
   :members:
   :undoc-members:
   :show-inheritance:
```

## Abstract Base (`haste.core.runners.base`)

Defines the interface all runner implementations must follow.

**Abstract methods:** `get_filecontent_from_task()`, `get_task_status()`, `add_task()`, `cleanup_task()`, `cancel_task()`

```{eval-rst}
.. automodule:: haste.core.runners.base
   :members:
   :undoc-members:
   :show-inheritance:
```

## Azure Batch Runner (`haste.core.runners.azure_batch`)

Executes tasks on Azure Batch GPU pools using Docker container images (pulled from Azure Container Registry).

- **`AzureBatchRunner`** — High-level runner implementing the base interface
- **`AzureBatchJob`** — Low-level Azure Batch job and task management

```{eval-rst}
.. automodule:: haste.core.runners.azure_batch
   :members:
   :undoc-members:
   :show-inheritance:
```
