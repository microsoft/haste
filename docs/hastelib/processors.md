# Processors

The `haste.core.processors` package contains the business logic layer for all HASTE operations. Processors coordinate between data layers, runners, and utilities to implement the platform's core functionality.

## Imagery (`haste.core.processors.imagery`)

Handles satellite imagery download, preprocessing, and Cloud Optimized GeoTIFF creation.

- **`ImageryPreProcessor`** — Queue imagery for async processing
- **`ImageryPostProcessor`** — Execute the full imagery preprocessing pipeline (download, mosaic, COG creation, tiling)
- **`ImageryLogRecord`** — Timestamped log record for imagery processing

```{eval-rst}
.. automodule:: haste.core.processors.imagery
   :members:
   :undoc-members:
   :show-inheritance:
```

## Training (`haste.core.processors.train`)

ML model training workflow management.

- **`BaseTrainProcessor`** — Base class for training operations
- **`TrainPreprocessor`** — Queue models for training (prepares experiment config)
- **`TrainPostprocessor`** — Execute and monitor training jobs on Azure Batch

```{eval-rst}
.. automodule:: haste.core.processors.train
   :members:
   :undoc-members:
   :show-inheritance:
```

## Inference (`haste.core.processors.inference`)

Model inference execution and monitoring.

- **`BaseInferenceProcessor`** — Base class for inference operations
- **`InferencePreprocessor`** — Prepare and queue model inference requests
- **`InferencePostprocessor`** — Execute and monitor inference jobs
- **`InferenceLogRecord`** — Timestamped inference log entry

```{eval-rst}
.. automodule:: haste.core.processors.inference
   :members:
   :undoc-members:
   :show-inheritance:
```

## Labels (`haste.core.processors.labels`)

Labeling task generation from imagery.

- **`LabelTaskGenerator`** — Generate labeling tasks from imagery layers with optional grid-based subdivision

```{eval-rst}
.. automodule:: haste.core.processors.labels
   :members:
   :undoc-members:
   :show-inheritance:
```

## Metadata (`haste.core.processors.metadata`)

High-level metadata operations over the data layer.

- **`MetadataProcessor`** — CRUD operations for project/model/user metadata with support for multiple storage backends

```{eval-rst}
.. automodule:: haste.core.processors.metadata
   :members:
   :undoc-members:
   :show-inheritance:
```

## Statistics (`haste.core.processors.stats`)

Project statistics aggregation.

- **`StatsPreProcessor`** — Queue stats update requests
- **`StatsPostProcessor`** — Process stats updates (add/update/delete project entries)

```{eval-rst}
.. automodule:: haste.core.processors.stats
   :members:
   :undoc-members:
   :show-inheritance:
```

## Artifacts (`haste.core.processors.artifacts`)

Model artifact management, packaging, and download.

- **`ArtifactProcessor`** — Manages model artifacts including zipping, downloading, and Azure Batch zip job submission

```{eval-rst}
.. automodule:: haste.core.processors.artifacts
   :members:
   :undoc-members:
   :show-inheritance:
```

## Uploader (`haste.core.processors.uploader`)

Chunked file upload handling.

- **`FileUploader`** — Process chunked file uploads with chunk storage and final assembly

```{eval-rst}
.. automodule:: haste.core.processors.uploader
   :members:
   :undoc-members:
   :show-inheritance:
```
