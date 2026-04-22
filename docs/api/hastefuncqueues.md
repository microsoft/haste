# HASTE Queue Processing Functions

Azure Functions for background queue processing in the HASTE platform. These 6 functions handle asynchronous tasks triggered by Azure Queue Storage messages.

## Queue Function Summary

| Function | Queue | Description |
|----------|-------|-------------|
| `GetProcessImageLayerQueueMessage` | Image queue | Download, preprocess, and tile satellite imagery (GDAL COG creation) |
| `GetCreateModelRunQueueMessage` | Train queue | Execute ML model training workflows via Azure Batch |
| `GetRunInferenceQueueMessage` | Inference queue | Run model inference on imagery for prediction generation |
| `UpdateStatsMessage` | Stats queue | Regenerate project-level statistics summaries |
| `GetArtifactsZipQueueMessage` | Zip queue | Package model artifacts (weights, predictions) for download |
| `ImagePoisonQueueHandler` | Image poison queue | Handle failed image processing messages for error recovery |

## Processing Pipelines

### Imagery Processing (`GetProcessImageLayerQueueMessage`)

1. Receive queue message with image layer configuration
2. Download pre/post-event imagery from configured source (Maxar, Planet, AWS S3, Azure Blob)
3. Preprocess with GDAL (mosaic, reproject, create Cloud Optimized GeoTIFF)
4. Generate labeling task files
5. Update project metadata and trigger stats refresh

### Model Training (`GetCreateModelRunQueueMessage`)

1. Receive queue message with model configuration
2. Prepare experiment config (hyperparameters, data paths, base model)
3. Submit training task to Azure Batch GPU pool
4. Monitor task progress (parse TensorBoard logs for metrics)
5. On completion, optionally auto-trigger inference

### Model Inference (`GetRunInferenceQueueMessage`)

1. Receive queue message with model and layer IDs
2. Prepare inference config (model checkpoint, imagery path, output settings)
3. Submit inference task to Azure Batch
4. Monitor task until completion
5. Store prediction results and update model metadata

## Auto-generated API Docs

```{eval-rst}
.. azure-function-module:: function_app
   :members:
   :undoc-members:
   :show-inheritance:
```
