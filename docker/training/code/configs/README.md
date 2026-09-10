# Standalone prediction configuration

The [configuration template](config.yml) requires two eager-result settings
when running `run_workflow.py` with `--step inference` or with no `--step`
(the default training-plus-inference workflow).

| Setting under `inference` | Requirement |
|---|---|
| `prediction_attrs_filename` | A JSON basename, not a path. The workflow writes it beside the prediction GeoPackage under `output_subdir`. |
| `prediction_revision` | A fresh, nonempty generation token for each prediction run. The template leaves it blank deliberately. |

The workflow checks both settings before starting inference or default-all
work. It does not silently omit attributes or invent a fallback revision.
Training-only execution (`--step training`) does not require these settings.

## Prepare each prediction run

Work from `docker/training/code` in an environment with `hastegeo` available.
Copy the template to a run-specific configuration, then generate a fresh token:

```bash
cp configs/config.yml configs/local-run.yml
python -c "from hastegeo.core.utils.metadata import MetadataUtils; print(MetadataUtils.generate_id())"
```

Put the printed value in `inference.prediction_revision` in the copied file.
Generate a new value for every new prediction generation, even for the same
model and imagery; do not keep a fixed example UUID or reuse an earlier token.

Use a fresh `output_subdir` for each generation, for example `outputs/` followed
by that generation's token. Changing the token alone does not protect files in
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

Choose one command per configured generation. Prepare a new token and output
directory before another prediction run. HASTE-managed jobs receive their
generation token and artifact filename from the backend; do not replace those
values with standalone examples.
