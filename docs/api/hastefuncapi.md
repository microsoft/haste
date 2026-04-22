# HASTE Function API

Azure Functions HTTP API for the HASTE platform. This module contains 28 REST endpoints for project management, file operations, annotations, models, inference runs, user management, and system administration.

## Endpoint Summary

### Projects & Dashboard

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/api/GetDashboardData` | `GetDashboardData` | Retrieve comprehensive dashboard statistics |
| GET | `/api/GetProjects` | `GetProjects` | Retrieve all projects with their statistics |
| GET | `/api/GetProjectDetails` | `GetProjectDetails` | Get details for a specific project |
| PUT | `/api/PutProject` | `PutProject` | Create or update a project |
| DELETE | `/api/DeleteProject` | `DeleteProject` | Delete a project |
| GET | `/api/GenerateProjectStats` | `GenerateProjectStats` | Regenerate project statistics |

### Image Layers

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| PUT | `/api/PutLayer` | `PutLayer` | Create/edit image layer, queue for processing |
| DELETE | `/api/DeleteLayer` | `DeleteLayer` | Delete image layer and associated models |
| GET | `/api/GetLayerDetailView` | `GetLayerDetailView` | Get image layer details with model count |

### Models & Training

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/api/GetLayerModelsDetails` | `GetLayerModelsDetails` | Get models for a specific layer |
| DELETE | `/api/DeleteModel` | `DeleteModel` | Delete a model and its artifacts |
| PUT | `/api/PutRunModelQueueMessage` | `PutRunModelQueueMessage` | Queue a training request |
| PUT | `/api/PutRunInferenceQueueMessage` | `PutRunInferenceQueueMessage` | Queue an inference request |
| PUT | `/api/PutCancelModelQueueMessage` | `PutCancelModelQueueMessage` | Cancel a training/inference job |
| PUT | `/api/PutArtifactsZipQueueMessage` | `PutArtifactsZipQueueMessage` | Queue artifact zipping request |
| GET | `/api/GetVisualizerResults` | `GetVisualizerResults` | Get visualization data for model results |

### Labels

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| PUT | `/api/PutLabelsFromLabelTool` | `PutLabelsFromLabelTool` | Save labels from labeling tool |
| GET | `/api/GetLayerLabelingToolData` | `GetLayerLabelingToolData` | Get label project data for annotation |

### Users

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/api/GetUsers` | `GetUsers` | Get all users with state validation |
| PUT | `/api/PutUser` | `PutUser` | Create/update/reinvite a user |
| DELETE | `/api/DeleteUser` | `DeleteUser` | Mark a user as deleted |
| GET | `/api/GetUserById` | `GetUserById` | Get a single user by ID |

### Admin & Settings

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/api/GetAdminSettings` | `GetAdminSettings` | Get admin configuration |
| PUT | `/api/PutAdminSettings` | `PutAdminSettings` | Update admin configuration |

### Model Catalog

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/api/GetModelCatalog` | `GetModelCatalog` | Get available base models with filters |
| PUT | `/api/PutModelCatalog` | `PutModelCatalog` | Add model to catalog |
| DELETE | `/api/DeleteModelCatalog` | `DeleteModelCatalog` | Remove model from catalog |

### File Upload

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| POST | `/api/UploadFileByChunk` | `UploadFileByChunk` | Upload large files in chunks |

## Auto-generated API Docs

```{eval-rst}
.. azure-function-module:: function_app
   :members:
   :undoc-members:
   :show-inheritance:
```
