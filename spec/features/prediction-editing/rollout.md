# Rollout: Versioned Prediction Editing

## Deploy

Deploy after the common-results stage, with compatible API/core and UI versions.
New raw predictions already carry sidecars. Every editor save creates its own
sidecar in the same request; no additional queue deployment is needed.

## Existing Versions

Do not migrate project data during implementation. A historical saved version
without attributes stays downloadable but is not falsely marked renderable.
The UI explains the missing artifact instead of starting a background job.

## Rollback

Roll back UI/API together. Saved version artifacts and additive metadata remain
in storage. The prior common-results viewer continues to access raw output.
Never rerun `data-init` or remove volumes as part of rollback.
