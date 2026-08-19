# Test plan: DINOv3-SAT building embeddings

## Unit tests

| Area | Cases |
|---|---|
| Model wrapper | Missing path, missing files, unsupported metadata, token stripping, output shape |
| Snapshot manifest | Exact SHA-256 and size verification, only two regular files, no directories or symlinks |
| Workflow factory | DINOv3 handle reports stride 16, feature dimension 1024, and ImageNet normalization |
| Processor | Configured prefix creates two exact model resources and task-local paths |
| Processor errors | Missing prefix rejects only DINOv3-SAT jobs |
| Queue errors | Configuration failures persist a failed model and clear status message |
| LocalRunner | Resource destinations remain inside the task directory; Blob names cannot traverse |
| Existing models | MOSAIKS and DINOv2 configurations remain unchanged |

## Integration tests

- Load a tiny mocked DINOv3 model with `local_files_only=True`,
  `trust_remote_code=False`, and `use_safetensors=True`.
- Confirm one output feature row remains aligned to each footprint.
- Require the training image build to import Transformers 5.3 and resolve the
  native DINOv3 model class without downloading weights.
- Confirm deployment templates, Docker Compose, and environment-drift checks
  include both DINOv3 model settings.

## UI validation

- DINOv3-SAT appears in the embedding dropdown.
- Selecting it sets resize factor 1 and batch size 1.
- Existing MOSAIKS and DINOv2 options retain their behavior.
- UI lint and production build succeed.

## Security validation

- No token, credential, or gated model file is committed.
- Runtime loading sets `local_files_only=True` and
  `trust_remote_code=False`.
- Runtime and image environments set `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1`.
- Runtime loading requires safetensors and rejects pickle-compatible formats.
- Model storage access uses existing managed identity or SAS behavior.
