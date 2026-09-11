# Rollout: Versioned Prediction Editing

## Deploy

Deploy after the common-results stage, with compatible API/core and UI versions.
New raw predictions already carry sidecars. Every editor save creates its own
sidecar in the same request; no additional queue deployment is needed.

The save-failure corrections require a newly built, matching `hastegeo` wheel
and API deployment. Redeploying only the UI, or retaining wheel `1.0.44rc11`,
does not apply them. No remote environment was changed during the investigation.
If a save still fails after deployment, its API log records safe exception/cause
classes, Azure status/error codes and failure locations without signed URLs or
request payloads. Client error messages remain intentionally sanitized.

## Existing Versions

Do not migrate project data during implementation. A historical saved version
without attributes stays downloadable but is not falsely marked renderable.
The UI explains the missing artifact instead of starting a background job.

## Rollback

Roll back UI/API together. Saved version artifacts and additive metadata remain
in storage. The prior common-results viewer continues to access raw output.
Never rerun `data-init` or remove volumes as part of rollback.
