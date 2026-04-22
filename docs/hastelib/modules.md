# HASTE Core Library (`haste_geo`)

The `haste-geo` package is the shared Python library used by all HASTE API services. It provides data models, storage backends, processing pipelines, and utilities for geospatial machine learning workflows.

## Package Structure

```
haste_geo/
├── core/
│   ├── config.py              — Environment-aware configuration
│   ├── artifact_storage/      — Artifact storage abstraction
│   │   ├── abstract_artifact_storage.py
│   │   ├── azure_blob_artifact_storage.py
│   │   ├── local_file_system_artifact_storage.py
│   │   └── unified_artifact_storage.py
│   ├── data_layer/            — Multi-backend data storage
│   │   ├── abstract_data_layer.py
│   │   ├── azure_blob_storage_data_layer.py
│   │   ├── azure_cosmos_db_data_layer.py
│   │   ├── azure_data_lake_data_layer.py
│   │   ├── azure_postgresql_data_layer.py
│   │   ├── local_file_system_data_layer.py
│   │   └── unified.py
│   ├── models/                — Pydantic data models
│   │   ├── admin.py
│   │   ├── projects.py
│   │   ├── stats.py
│   │   ├── training.py
│   │   ├── uploader.py
│   │   ├── users.py
│   │   └── visualizer.py
│   ├── processors/            — Business logic processors
│   │   ├── artifacts.py
│   │   ├── imagery.py
│   │   ├── inference.py
│   │   ├── labels.py
│   │   ├── metadata.py
│   │   ├── stats.py
│   │   ├── train.py
│   │   └── uploader.py
│   ├── runners/               — Task execution backends
│   │   ├── base.py
│   │   ├── azure_batch.py
│   │   ├── local.py
│   │   └── unified_runner.py
│   └── utils/                 — Shared utilities
│       ├── artifacts.py
│       ├── data.py
│       ├── downloader.py
│       ├── exceptions.py
│       ├── imagery.py
│       ├── logs.py
│       ├── metadata.py
│       ├── queues.py
│       ├── tbparser.py
│       └── user.py
└── workflows/                 — CLI workflow entry points
    ├── prepare_imagery.py
    └── zip_artifacts.py
```

## Installation

The package is installed as an editable dependency from the repository root:

```bash
pip install -e hastelib/
```

Or via the conda environment:

```bash
conda env create -f env.yml
conda activate haste_env
```
