# Data Models

The `hastegeo.core.models` package contains Pydantic data models used throughout the HASTE platform for validation, serialization, and type safety.

## Projects (`hastegeo.core.models.projects`)

Core domain models for HASTE projects:

- **`PrimaryClass`** — Damage/feature classification definition
- **`Geometry`** — GeoJSON-style geometry (point, polygon, linestring, etc.)
- **`Properties`** — Feature properties with classification and metadata
- **`Label`** — Individual annotation for imagery
- **`LabelingImagery`** — Imagery display configuration for the labeling tool
- **`Feature`** — Geographic feature for labeling tasks
- **`LabelProject`** — Complete labeling project with features, labels, and imagery config
- **`TrainingJob`** — ML training job metadata (status, epochs, timing)
- **`InferenceJob`** — Model inference job execution metadata
- **`Checkpoint`** — Model checkpoint state persistence
- **`ModelRequest`** — Request to create/configure a model
- **`Model`** — Complete ML model configuration and lifecycle
- **`ZipTypeEnum`** — Enum for zip job types (TRAINING, INFERENCE)
- **`ZipJob`** — File archiving job for model artifacts
- **`ModelArtifacts`** — Model artifact management and packaging state

```{eval-rst}
.. automodule:: hastegeo.core.models.projects
   :members:
   :undoc-members:
   :show-inheritance:
```

## Admin (`hastegeo.core.models.admin`)

Administrative configuration models:

- **`SourceType`** — Imagery source configuration
- **`BaseModels`** — Base model artifact metadata
- **`DrawingTools`** — Labeling tool drawing capabilities (polygon, rectangle, circle)
- **`Grid`** — Grid visualization settings
- **`DefaultPrimaryClass`** — Default classification for labeling
- **`LabelingToolSettings`** — Complete labeling UI configuration
- **`AdminConfig`** — Administrative configuration container

```{eval-rst}
.. automodule:: hastegeo.core.models.admin
   :members:
   :undoc-members:
   :show-inheritance:
```

## Training (`hastegeo.core.models.training`)

ML training and experiment configuration:

- **`ModelSource`** (Enum) — Model source: HASTE or EXTERNAL
- **`Imagery`** — Imagery normalization and channel configuration
- **`Inference`** — Inference job configuration (batch size, GPU, output path)
- **`Labels`** — Training label configuration
- **`Training`** — Training hyperparameters (learning rate, batch size, epochs, GPU)
- **`ExperimentConfig`** — Complete experiment configuration for training
- **`CatalogModel`** — Model catalog entry with metadata

```{eval-rst}
.. automodule:: hastegeo.core.models.training
   :members:
   :undoc-members:
   :show-inheritance:
```

## Statistics (`hastegeo.core.models.stats`)

Project statistics models:

- **`ImageLayerStats`** — Statistics for an image layer (ID, label count)
- **`ProjectStats`** — Project-level statistics (layers, models, labels, countries)
- **`StatsRequest`** — Request to update project statistics
- **`ProjectsSummary`** — Container for all project statistics

```{eval-rst}
.. automodule:: hastegeo.core.models.stats
   :members:
   :undoc-members:
   :show-inheritance:
```

## Users (`hastegeo.core.models.users`)

User management models:

- **`User`** — User profile and role information
- **`Users`** — Container for list of users
- **`Invite`** — Invitation with email, roles, link, and send status
- **`Invites`** — Container for list of invitations
- **`AddUsersRequest`** — Request to add multiple users with roles

```{eval-rst}
.. automodule:: hastegeo.core.models.users
   :members:
   :undoc-members:
   :show-inheritance:
```

## Visualizer (`hastegeo.core.models.visualizer`)

Visualization configuration:

- **`Imagery`** — Imagery layer configuration (URL, TMS, attribution, zoom bounds)
- **`Visualizer`** — Visualization config with pre/post event imagery and damage predictions

```{eval-rst}
.. automodule:: hastegeo.core.models.visualizer
   :members:
   :undoc-members:
   :show-inheritance:
```

## Uploader (`hastegeo.core.models.uploader`)

File upload models:

- **`FileUploadRequest`** — File upload status and progress tracking

```{eval-rst}
.. automodule:: hastegeo.core.models.uploader
   :members:
   :undoc-members:
   :show-inheritance:
```
