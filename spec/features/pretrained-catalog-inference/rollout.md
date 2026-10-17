# Rollout: Pretrained Catalog Inference

**Contents:** [Runtime](#application-and-runtime) -
[DINOv3](#dinov3-registration) - [DINOv2](#dinov2-follow-up-options) -
[Deployment](#deployment-and-rollback)

## Application and Runtime

Build and validate locally first. Keep the existing development data and avoid
`data-init`, volume resets and blanket Compose recreation. Only recreate
affected services with `--no-deps`; restart api-proxy after API recreation.

Build the additional `transformerinference_image` Compose service; its ML
dependencies are isolated from `training_image`. Both API and queues receive
`AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE`. Hosted deployments use
`hastetransformerinference` with the matching wheel/image tag; Bicep's optional
`transformerInferenceImage` parameter configures
the function apps and Batch pool image list. Leaving it empty disables transformer
selection rather than routing its checkpoint into the training image.

The local image is `haste-transformerinference`, built from the
`transformerinference-runtime` target in `docker/training/Dockerfile` using
`docker/transformerinference/requirements.txt`. Dependencies and supported model
adapters are unchanged by the image rename. Existing run snapshots retain their
original image references; keep those local tags available rather than rewriting
historical model records.

## DINOv3 Registration

Register the initial DINOv3 model only after asset/hash/runtime checks succeed.
Use an idempotent registration command, not catalog replacement.

The accepted original-any recipe uses the checkpoint's embedded run directory,
the pinned source's class mapping, and an authorized Hugging Face config export.
The artifact is epoch 12 / step 8190; do not assign the source document's separate
15-epoch evaluation metrics to it.

After offline acceptance, import using the configured HASTE storage:

```bash
PYTHONPATH=hastelib/src conda run -n haste \
  python -m hastegeo.core.processors.catalog_import \
  --recipe localtmp/pretrained-assets/dinov3-original-any-catalog-model-torch-2.10.0.json \
  --checkpoint localtmp/pretrained-assets/xview2_dinov3_upernet_any-last.ckpt \
  --backbone-config localtmp/pretrained-assets/hf-config/114c1379950215c8b35dfcd4e90a5c251dde0d32/config.expanded.json
```

The importer checks local and stored SHA-256 values, uses content-addressed asset
paths, preserves other catalog entries, and treats an identical import as a
no-op. A conflicting catalog name or corrupt existing asset fails instead of
being replaced. Recipe JSON is operator-supplied acceptance metadata, not proof
by itself that GPU inference was exercised. Keep binary assets out of Git.

## DINOv2 Follow-Up Options

The importer includes all six accepted `dinov2_followups_20260927` recipes:

| Condition | Seed | Selected update |
|---|---|---|
| original_only | 0 | 48884 |
| original_only | 1 | 53328 |
| original_only | 2 | 51106 |
| source_balanced_50_50 | 0 | 57772 |
| source_balanced_50_50 | 1 | 55550 |
| source_balanced_50_50 | 2 | 42218 |

Download the authorized checkpoint files separately, preserving the manifest's
`<condition>/seed_00N_update_0NNNNN.ckpt` paths under one local directory.
Do not put SAS URLs in recipes, commands, logs or source control. The importer
does not download assets or deserialize checkpoints; it verifies every pinned
local hash before importing any model, then verifies controlled stored content.
Each checkpoint carries its own offline backbone configuration.

After configuring the intended HASTE storage environment, explicitly register:

```bash
PYTHONPATH=hastelib/src conda run -n haste \
  python -m hastegeo.core.processors.catalog_import \
  --dinov2-followups /path/to/dinov2_followups_20260927 \
  --catalogued-by operator@example.com
```

This adds six options without replacing other catalog entries. Repeating the
same import is a no-op. A conflicting existing name fails rather than overwrites;
completed imports remain available if a later storage operation fails.
Registration is explicit, never a startup seed or `data-init` operation.

## Deployment and Rollback

Remote publication and PR creation require explicit user authorization. A
later deployment must use matching branch wheel, API/worker/UI and GPU-image
versions rather than the default latest stable wheel.

Rollback application/image selection without deleting catalog snapshots,
source models, imported assets or generated inference results.

The original DINOv3 local rollout recreated only API, queues and UI with `--no-deps --no-build`,
then restarted `api-proxy`. Azurite and `data-init` were not recreated. The
previous API, queues, UI and training images are retained under the
`before-catalog-inference` tag on their respective `haste-*` repositories.
Temporary candidate services and `catalog-check-*` queues were removed after
their work drained; completed model records and artifacts remain available.
The September 29 rebase/DINOv2 work does not restart that stack or register
models into its live catalog.
