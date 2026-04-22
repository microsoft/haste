# API Modules

The HASTE API provides a comprehensive set of Azure Functions for managing geospatial machine learning workflows. The API is organized into three functional areas:

## Architecture Overview

The HASTE API follows a microservices architecture with clear separation of concerns:

**REST API Functions** (`hastefuncapi`)
: 28 synchronous HTTP endpoints for real-time operations including project management, user interactions, file uploads, labeling, model configuration, and system administration.

**Queue Processing Functions** (`hastefuncqueues`)
: 6 asynchronous background workers for compute-intensive tasks such as image preprocessing, model training, inference execution, statistics aggregation, and artifact packaging.

**Tile Server** (`titilerfuncapi`)
: A TiTiler-based tile server for serving Cloud Optimized GeoTIFF imagery tiles, STAC catalog access, and mosaic generation.

This design ensures:

- **Scalability**: Independent scaling of API, processing, and tile-serving workloads
- **Reliability**: Queue-based processing with retry logic, poison queue handling, and error recovery
- **Performance**: Non-blocking operations for time-consuming tasks via Azure Queue Storage
- **Monitoring**: Comprehensive logging and telemetry across all operations

:::{note}
The function_app modules use Azure Functions decorators and require specific environment configuration including Azure Storage, Cosmos DB, Azure Batch, and compute resources for full functionality. See the {doc}`../getting-started` guide for configuration details.
:::
