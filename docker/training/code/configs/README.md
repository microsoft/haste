# Standalone prediction configuration

The [configuration template](config.yml) requires two eager-result settings
when running `run_workflow.py` with `--step inference` or with no `--step`
(the default training-plus-inference workflow).

| Setting under `inference` | Requirement |
|---|---|
| `prediction_attrs_filename` | A JSON basename, not a path. The workflow writes it beside the prediction GeoPackage under `output_subdir`. |
| `prediction_revision` | A unique ID for one prediction output, normally a UUIDv4. The template leaves it blank deliberately. |

The workflow checks both settings before starting inference or default-all
work. It does not silently omit attributes or invent a fallback revision.
Training-only execution (`--step training`) does not require these settings.

## What `prediction_revision` identifies

The revision identifies one newly generated GeoPackage/attribute-JSON pair,
even when the model and imagery have not changed. It is an opaque output ID,
not an authentication token, checkpoint version, content hash, or saved-edit
version number. It contains no credentials.

The workflow writes this value into the JSON sidecar as `predictionRevision`.
For HASTE-managed runs, the backend checks it against the submitted run's ID
before publishing the pair on `Model`. The API includes that revision in
artifact URLs, and the viewer checks the sidecar against the selected result.
This prevents a new result from being confused with an older sidecar.

HASTE-managed inference uses its task ID, `inf-<UUIDv4>`, for this value.
Standalone runs can use a plain UUIDv4 generated once when preparing the run,
as below. Do not generate separate IDs for the GeoPackage and its sidecar.

## Prepare each prediction run

Work from `docker/training/code` in an environment with `hastegeo` available.
Copy the template to a run-specific configuration, then generate a UUIDv4:

```bash
cp configs/config.yml configs/local-run.yml
python -c "import uuid; print(uuid.uuid4())"
```

Put the printed value in `inference.prediction_revision` in the copied file.
This is the same UUIDv4 generation used by `MetadataUtils.generate_id()`.
Generate a new value for every new prediction generation, even for the same
model and imagery; do not keep a fixed example UUID or reuse an earlier ID.

Use a fresh `output_subdir` for each generation, for example `outputs/` followed
by that generation's ID. Changing the ID alone does not protect files in
a reused output directory from replacement. Keep the filename a basename,
such as `prediction_attrs.json`, without including the directory.

Complete the existing project-specific paths and other settings as usual;
the template is not a self-contained runnable dataset. Then run either:

```bash
# Existing trained checkpoint; run inference and eagerly write attributes.
python run_workflow.py --config configs/local-run.yml --step inference

# Alternatively, train and infer; omitting --step selects both.
python run_workflow.py --config configs/local-run.yml
```

Choose one command per configured generation. Prepare a new revision and output
directory before another prediction run. HASTE-managed jobs receive their
revision and artifact filename from the backend; do not replace those
values with standalone examples.
