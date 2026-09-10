# ADR 0005: Catalog Models Without Target Fine-Tuning

## Status

Accepted for implementation on the main-based pretrained inference branch.

## Decision

Represent each catalog inference invocation as a separate inference-only Model
record. Snapshot an allowlisted adapter and compatible checkpoint/input recipe,
then use the existing inference queue, UnifiedRunner and output pipeline.

The initial adapters are legacy HASTE and DINOv3 UPerNet. Do not infer arbitrary
architectures from filenames, accept executable catalog configuration, or
require target training artifacts.

Stage controlled, integrity-checked assets and offline configuration. Preserve
source-model behavior and result formats, including explicit class mapping and
NoData handling. Keep the public catalog storage compatible.

Transformer models use a dedicated `transformerinference-runtime` image target with a compatible ML
dependencies. The default training image remains on its original Torch stack.
`AZURE_BATCH_TRANSFORMER_INFERENCE_DOCKER_IMAGE` selects this target for both API eligibility
and workers; unset configuration leaves DINOv3 unavailable. Each run snapshots
its selected image reference. Local Compose, RC image builds, application
deployment, and Batch pool image lists carry this separate image explicitly.
DINOv3 remains the first supported transformer adapter; the generic image name
does not imply support for arbitrary transformer checkpoints.

## Consequences

Model results remain discoverable through existing layer/model views. Separate
runs do not overwrite prior results, and the catalog is not a mutable pointer
to an in-progress inference. Dependencies must support both execution targets
without regressing existing models. No new inference queue or unmerged result
framework is introduced.
