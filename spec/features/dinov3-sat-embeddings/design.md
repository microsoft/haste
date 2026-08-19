# Technical design: DINOv3-SAT building embeddings

## Table of contents

- [Overview](#overview)
- [Runtime flow](#runtime-flow)
- [Model contract](#model-contract)
- [Configuration](#configuration)
- [Failure behavior](#failure-behavior)

## Overview

HASTE uses the Hugging Face representation of Meta's DINOv3 ViT-L/16
SAT-493M backbone:
`facebook/dinov3-vitl16-pretrain-sat493m`. The model is gated, so an
administrator downloads an approved immutable snapshot once and uploads its
files to HASTE-controlled Blob Storage.

The Function and Batch services never receive a Hugging Face token. Azure
Batch stages the snapshot into the task working directory through the same
managed resource-file mechanism used for imagery and footprints.

## Runtime flow

```text
Admin-approved HF snapshot
        |
        v
HASTE Blob Storage prefix
        |
        v
EmbeddingPostprocessor resource files
        |
        v
Batch task inputs/models/dinov3_sat/
        |
        v
AutoModel.from_pretrained(local_files_only=True)
        |
        v
patch tokens -> footprint pooling -> existing artifacts
```

No API endpoint or persisted model schema change is required. The existing
`Model.embeddingModel` string carries the new `dinov3_sat` identifier.

## Model contract

The workflow adapter must:

- accept normalized `(B, 3, H, W)` tensors where `H` and `W` are multiples of
  16;
- load only from the staged local directory;
- remove the CLS token and all register tokens;
- return patch tokens shaped `(B, H/16 * W/16, 1024)`;
- use ImageNet normalization, matching the reference implementation in
  `~/src/haste-developement/xview2_damage/embedders/hub_backbones.py`;
- preserve existing crop, mask, pooling, feature-sidecar, and row-order logic.

## Configuration

| Setting | Required | Description |
|---|---|---|
| `DINOV3_SAT_MODEL_BLOB_PREFIX` | For DINOv3-SAT jobs | Blob prefix containing `config.json` and `model.safetensors`. |
| `DINOV3_SAT_MODEL_CONTAINER_URL` | No | Separate container URL; defaults to HASTE artifact storage. |

The snapshot is resolved to `inputs/models/dinov3_sat` in each Batch task.
The workflow receives that relative path in `files.model`.

## Failure behavior

- Reject DINOv3-SAT submission when the Blob prefix is not configured.
- Fail clearly when required snapshot files are absent.
- Use `local_files_only=True` and `trust_remote_code=False`; never fall back to
  network download or executable model repository code.
- Validate model type, patch size, hidden size, and register-token metadata
  before inference.

