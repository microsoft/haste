# Rollout: Pretrained Catalog Inference

Build and validate locally first. Keep the existing development data and avoid
`data-init`, volume resets and blanket Compose recreation. Only recreate
affected services with `--no-deps`; restart api-proxy after API recreation.

Build the additional `transformerinference_image` Compose service; its ML
dependencies are isolated from `training_image`. Both API and queues receive
`AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE`. Hosted deployments use
`hastetransformerinference` with the matching wheel/image tag; Bicep's optional
`transformerInferenceImage` parameter configures
the function apps and Batch pool image list. Leaving it empty disables DINOv3
selection rather than routing its checkpoint into the training image.

The local image is `haste-transformerinference`, built from the
`transformerinference-runtime` target in `docker/training/Dockerfile` using
`docker/transformerinference/requirements.txt`. Dependencies and supported model
adapters are unchanged by the image rename. Existing run snapshots retain their
original image references; keep those local tags available rather than rewriting
historical model records.

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

Remote publication and PR creation require explicit user authorization. A
later deployment must use matching branch wheel, API/worker/UI and GPU-image
versions rather than the default latest stable wheel.

Rollback application/image selection without deleting catalog snapshots,
source models, imported assets or generated inference results.

Local rollout recreated only API, queues and UI with `--no-deps --no-build`,
then restarted `api-proxy`. Azurite and `data-init` were not recreated. The
previous API, queues, UI and training images are retained under the
`before-catalog-inference` tag on their respective `haste-*` repositories.
Temporary candidate services and `catalog-check-*` queues were removed after
their work drained; completed model records and artifacts remain available.
