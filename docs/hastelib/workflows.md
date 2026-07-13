# Workflows

The `hastegeo.workflows` package contains CLI entry points for standalone workflow execution. These are registered as console scripts in `pyproject.toml`.

## CLI Entry Points

| Command | Module | Description |
|---------|--------|-------------|
| `prepare-imagery` | `hastegeo.workflows.prepare_imagery:main` | Run the full imagery preprocessing pipeline |
| `zip-artifacts` | `hastegeo.workflows.zip_artifacts:main` | Zip model artifacts for download |

## Imagery Preparation (`hastegeo.workflows.prepare_imagery`)

Orchestrates the complete imagery preprocessing pipeline:

1. Download pre-event and post-event imagery from configured sources
2. Mosaic multiple tiles into a single raster
3. Create Cloud Optimized GeoTIFF (COG) output
4. Upload processed imagery to storage

- **`ImageryWorkflow`** — Main workflow class

```{eval-rst}
.. automodule:: hastegeo.workflows.prepare_imagery
   :members:
   :undoc-members:
   :show-inheritance:
```

## Artifact Zipping (`hastegeo.workflows.zip_artifacts`)

Packages model artifacts (training outputs, inference predictions) into ZIP archives for download.

```{eval-rst}
.. automodule:: hastegeo.workflows.zip_artifacts
   :members:
   :undoc-members:
   :show-inheritance:
```
