# User stories: Keyless storage

## Stories

| Story | Acceptance criteria |
|---|---|
| S1: Operate without storage keys | API, queues, workers, downloads and publishing work with the Blob connection string absent; Azure read links use user delegation |
| S2: Limit delegated reads | One-blob read-only tokens; trusted project/layer linkage; foreign account/container/project refused before signing; metadata stays unsigned |
| S3: Preserve long sessions | Label edits and prediction selection survive token refresh, tab resume and retry; stale refreshes do not overwrite current results |
| S4: Remove the File mount key | Blob-staged uploads survive instance changes; scratch is disposable; restart loses no durable output; retained share is untouched |
| S5: Validate safely before promotion | Maintainer-dispatched candidate can deploy only to dev1; exact source and attestation checks remain; prod is main-only |
| S6: Retire Shared Key safely | Separate approved per-account disablement, positive identity and negative key tests, redeployment persistence and rollback record |

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
|---|---|---|
| S1 | backend-dev | backend-validation |
| S2 | backend-dev, gis | backend-validation |
| S3 | ui | ui-validation |
| S4 | backend-dev | backend-validation |
| S5 | backend-dev | backend-validation |
| S6 | backend-dev | backend-validation |

Agent names identify ownership; they do not require parallel delegation.
