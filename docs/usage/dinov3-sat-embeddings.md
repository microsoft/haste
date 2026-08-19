# Configure DINOv3-SAT embeddings

## Table of contents

- [Model provenance](#model-provenance)
- [Download the approved snapshot](#download-the-approved-snapshot)
- [Upload the snapshot](#upload-the-snapshot)
- [Configure HASTE](#configure-haste)
- [Run an embedding](#run-an-embedding)
- [Troubleshooting](#troubleshooting)

## Model provenance

HASTE's `dinov3_sat` option uses Meta's satellite-pretrained DINOv3
ViT-L/16 model:

| Property | Value |
|---|---|
| Hugging Face repository | `facebook/dinov3-vitl16-pretrain-sat493m` |
| Reference revision | `f692fa42da72c6797b67cd73494a168d1120d3ee` |
| Pretraining dataset | SAT-493M |
| Patch size | 16 pixels |
| Output dimension | 1024 |
| Required files | `config.json`, `model.safetensors` |

This is the Hugging Face equivalent of the `dinov3_sat` setup evaluated in
`~/src/haste-developement/xview2_damage/embedders/dinov3_hf.py` and
`hub_backbones.py`. HASTE uses ImageNet normalization to match that reference
pipeline.

The model is gated. Review and accept Meta's license and obtain access through
Hugging Face before downloading it. Do not commit the model, a Hugging Face
token, or generated credentials to the HASTE repository.

## Download the approved snapshot

Authenticate interactively on an administration workstation:

```bash
hf auth login
```

Download the pinned snapshot:

```bash
hf download facebook/dinov3-vitl16-pretrain-sat493m \
  config.json model.safetensors \
  --revision f692fa42da72c6797b67cd73494a168d1120d3ee \
  --local-dir ./dinov3_sat
```

The explicit file list is required because HASTE rejects repository
documentation, Python code, hidden files, and other unapproved snapshot
content. Confirm that the download directory contains only:

```text
dinov3_sat/
├── config.json
└── model.safetensors
```

Verify the evaluated snapshot:

```bash
sha256sum dinov3_sat/config.json dinov3_sat/model.safetensors
```

Expected SHA-256 values:

```text
135ecd23e34a70b6fbed8b083fdecb319b7e3a54e3d849258bbe4ddcf1783bb5  config.json
4e6356d992c1301b5e7c275f465e47296c5c4ad17052e262b29fc21e82ccc698  model.safetensors
```

Expected sizes are 745 bytes for `config.json` and 1,212,559,808 bytes for
`model.safetensors`. HASTE verifies these hashes and sizes before loading the
model. Do not add PyTorch pickle checkpoints (`.bin`, `.pt`, or `.pth`),
Python source, symlinks, or unrelated files to the snapshot prefix.

## Upload the snapshot

Upload both files to a HASTE-controlled private Blob container. Keep the
revision in the prefix so upgrades are explicit:

```bash
az storage blob upload-batch \
  --account-name <storage-account> \
  --destination <artifact-container> \
  --destination-path embedding-models/dinov3_sat/f692fa42 \
  --source ./dinov3_sat \
  --auth-mode login
```

Grant the Azure Batch identity read access to this container. HASTE stages the
snapshot as a Batch resource under:

```text
inputs/models/dinov3_sat/
```

The training image does not contain the gated weights, and Batch jobs never
contact Hugging Face.

## Configure HASTE

Set these application settings on the queue-processing Function App:

| Setting | Required | Example |
|---|---|---|
| `DINOV3_SAT_MODEL_BLOB_PREFIX` | Yes | `embedding-models/dinov3_sat/f692fa42` |
| `DINOV3_SAT_MODEL_CONTAINER_URL` | Only for a separate container | `https://<account>.blob.core.windows.net/<container>` |

If `DINOV3_SAT_MODEL_CONTAINER_URL` is omitted, HASTE uses the configured
artifact storage container. For local Docker development, set the same values
on `hastefuncqueues` and upload the snapshot to the configured Azurite
container.

Configure a bare HTTPS container URL only. Do not append a SAS query string;
HASTE rejects query-bearing URLs to prevent credentials from entering resource
diagnostics. Use the existing managed identity or runner-generated SAS flow.

Restart the queue service after changing application settings.

## Run an embedding

Follow [Rapid Building Assessment](rapid-building-assessment.md). In the
**New Embedding** dialog, choose **DINOv3-SAT ViT-L/16 (1024-dim)**.

The recommended initial settings are:

- resize factor: `1`;
- batch size: `1`.

DINOv3-SAT is substantially larger than the DINOv2 options. Increase batch
size only after observing available GPU memory on the configured Batch pool.

## Troubleshooting

| Message | Resolution |
|---|---|
| Model Blob prefix is not configured | Set `DINOV3_SAT_MODEL_BLOB_PREFIX` on the queue service. |
| `config.json` or `model.safetensors` is missing | Upload the complete pinned snapshot at the configured prefix. |
| Model metadata does not report ViT-L/16 and 1024 dimensions | Restore the documented SAT-493M snapshot instead of using another DINOv3 variant. |
| Batch receives 403 while staging model files | Grant the Batch identity Blob Data Reader access or correct the container URL/SAS configuration. |
| GPU out of memory | Use batch size `1` or a larger GPU pool. |
