# Data Model: Pretrained Catalog Inference

## Catalog

Preserve existing CatalogModel fields and name uniqueness. Optional
`capabilities` and `inferenceSpec` distinguish inference-only DINOv3 assets from
existing training bases. The spec contains an allowlisted adapter, credential-
free checkpoint/configuration references, hashes, backbone/grouping provenance,
input contract and runtime settings. Legacy recipes include the compatible
source experiment configuration.

## Run

Reuse Model with `modelType=pretrained`, `catalogModelName`,
`inferenceRequestId`, `inferenceImage`, and `pretrainedInference` containing the
resolved snapshot. `inferenceInputs` stores credential-free source references.
Training fields/jobs are not fabricated. Existing inference status, task IDs,
job list and result pointers remain the run's execution/output state.

Use a unique project-scoped model ID and unique task/output namespace. The
request UUID provides idempotent submission identity, not a shared active-result
pointer. Queues carry identities; asset credentials are generated only when
staging resources. Removing a catalog entry does not remove run snapshots or
artifacts.

`ModelArtifacts.zipFailures` bounds retries for catalog-run archive packaging.
An archive failure does not change the successful inference state.
