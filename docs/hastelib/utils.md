# Utilities

The `haste.core.utils` package provides shared utility modules used across the HASTE platform.

## Logging (`haste.core.utils.logs`)

Static logger utility for consistent logging across all HASTE components.

- **`Logger`** — Configurable logger with file and console handlers

```{eval-rst}
.. automodule:: haste.core.utils.logs
   :members:
   :undoc-members:
   :show-inheritance:
```

## Metadata (`haste.core.utils.metadata`)

Utility functions for ID generation, timestamps, and hashing.

- **`MetadataUtils`** — Static methods: `generate_id()`, `generate_int_id()`, `get_timestamp()`, `get_short_date()`, `hash_string()`, `append_status_message()`

```{eval-rst}
.. automodule:: haste.core.utils.metadata
   :members:
   :undoc-members:
   :show-inheritance:
```

## Queue Handler (`haste.core.utils.queues`)

Azure Queue Storage client for sending and receiving async task messages.

- **`AzureQueueHandler`** — Queue operations: `put_message()`, `get_messages()`, `delete_message()`

```{eval-rst}
.. automodule:: haste.core.utils.queues
   :members:
   :undoc-members:
   :show-inheritance:
```

## Imagery (`haste.core.utils.imagery`)

Geospatial imagery processing utilities using GDAL, rasterio, and OpenCV.

- **`ImageryUtils`** — Static methods for mosaic creation, COG generation, reprojection, and tile creation

```{eval-rst}
.. automodule:: haste.core.utils.imagery
   :members:
   :undoc-members:
   :show-inheritance:
```

## Downloader (`haste.core.utils.downloader`)

Multi-source imagery download client.

- **`ImageryDownloader`** — Downloads from HTTP URLs, Azure Blob Storage, and AWS S3 with retry logic

```{eval-rst}
.. automodule:: haste.core.utils.downloader
   :members:
   :undoc-members:
   :show-inheritance:
```

## Data Utilities (`haste.core.utils.data`)

Data transformation and file management helpers.

- `extract_from_url()` — Extract substring from URL using regex
- `convert_json_to_geojson()` — Transform JSON to GeoJSON FeatureCollection
- `get_distinct_label_classes()` — Extract unique classification labels
- `directory_cleanup()` — Delete directory and contents
- `filter_roles()` — Filter out anonymous/authenticated roles

```{eval-rst}
.. automodule:: haste.core.utils.data
   :members:
   :undoc-members:
   :show-inheritance:
```

## TensorBoard Parser (`haste.core.utils.tbparser`)

Parse TensorBoard event logs to extract training metrics.

- `parse_tb_event_logs()` — Parse event logs into epochs, accuracy, loss
- `calculate_metrics()` — Calculate training progress metrics

```{eval-rst}
.. automodule:: haste.core.utils.tbparser
   :members:
   :undoc-members:
   :show-inheritance:
```

## User Management (`haste.core.utils.user`)

User invitation and email notification utilities.

- **`InvitationManager`** — Manage invitations via Azure Static Web Apps API and send emails via Azure Communication Services
- **`EmailSendResponse`** / **`CreateInvitationResponse`** — Response types

```{eval-rst}
.. automodule:: haste.core.utils.user
   :members:
   :undoc-members:
   :show-inheritance:
```

## Exceptions (`haste.core.utils.exceptions`)

Custom exception types.

- **`UnsupportedFormatError`** — Raised for unsupported file formats

```{eval-rst}
.. automodule:: haste.core.utils.exceptions
   :members:
   :undoc-members:
   :show-inheritance:
```
