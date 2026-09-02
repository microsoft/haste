# Data Model: Backend-neutral compute runner + Azure Machine Learning backend

This feature changes no Cosmos container, Blob container, Data Lake path, or
Queue message schema. It adds a new validated core model module and an
optional field on four existing job records. See [design.md](design.md) for
behavior and [test-plan.md](test-plan.md) for model-level test coverage.

## Core Model Changes (`hastelib`)

### New module: `hastegeo.core.models.compute`

#### Enumerations

| Enum | Values |
|---|---|
| `ComputeBackend` | `local`, `azure_batch`, `azure_ml`, `auto` |
| `ComputeWorkload` | `training`, `inference`, `embedding`, `imagery_preparation`, `artifact_packaging` |
| `ComputeJobState` | `pending`, `submitting`, `queued`, `preparing`, `running`, `succeeded`, `failed`, `cancelled` |
| `InputKind` | `file`, `folder` |
| `InputDeliveryMode` | `download`, `mount`, `direct` |
| `OutputPersistenceMode` | `live_mount`, `upload_on_completion` |
| `CapacityState` | `available`, `queueable`, `unavailable`, `unknown` |

#### `ComputeJobSpec` (Pydantic `BaseModel`)

```json
{
  "executionId": "string — deterministic HASTE execution identifier, generated before submission",
  "workload": "ComputeWorkload",
  "backendPreference": "ComputeBackend",
  "container": {
    "imageReference": "string — container image tag or digest; any value is accepted except the mutable ':latest' tag in deployed environments",
    "environmentReference": "string | null — resolved AML environment version, adapter-populated; must be a specific immutable version (not ':latest'/'@latest') in deployed environments when set",
    "workingDirectory": "string — HASTE_JOB_WORKDIR-relative root"
  },
  "command": "string — internal trusted shell command, never built from untrusted input",
  "inputs": [
    {
      "sourceUri": "string",
      "kind": "InputKind",
      "destinationRelativePath": "string — no leading '/' or '..' segments",
      "deliveryMode": "InputDeliveryMode"
    }
  ],
  "outputs": [
    {
      "name": "string",
      "sourceRelativePattern": "string — must resolve inside the job workspace",
      "destinationUri": "string — HASTE storage prefix",
      "persistenceMode": "OutputPersistenceMode"
    }
  ],
  "environment": "map[string, string] — non-secret only",
  "resources": {
    "accelerator": "string | null",
    "nodeCount": "int",
    "sharedMemoryMb": "int | null",
    "allowSpot": "bool",
    "targetOverride": "string | null"
  },
  "timeoutSeconds": "int",
  "tags": {
    "project": "string",
    "imageLayer": "string | null",
    "model": "string | null",
    "task": "string | null",
    "workload": "ComputeWorkload",
    "hasteVersion": "string"
  }
}
```

**Validation rules:**

- reject absolute destination-relative input paths and `..` traversal;
- reject output patterns that resolve outside the logical job workspace;
- reject unrecognized URI schemes on `sourceUri`/`destinationUri`;
- reject the mutable `:latest` tag on `imageReference` in deployed
  environments only — any other tag or an `@sha256:<digest>` reference is
  accepted, so an existing Azure Batch deployment pinning a versioned,
  non-digest tag (e.g. `:v1.2.3`) is unaffected;
- require `environmentReference` (when set — AML-specific, adapter-resolved)
  to reference a specific immutable AML environment version, not a
  `:latest`/`@latest` alias, in deployed environments;
- require the resolved backend to declare capability for `workload`;
- reject any credential, token, or signed query string in `environment` or
  `tags` (checked at construction and before every log line).

#### `ComputeJobHandle` (Pydantic `BaseModel`, persisted)

```json
{
  "executionId": "string",
  "requestedBackend": "ComputeBackend",
  "selectedBackend": "ComputeBackend — never 'auto'",
  "backendProfile": "string — named adapter configuration profile",
  "providerJobId": "string",
  "providerTaskId": "string | null",
  "targetId": "string — pool id / compute cluster name / local execution id",
  "outputUri": "string — HASTE storage output prefix",
  "submittedAt": "ISO 8601 datetime",
  "routingReason": "string — why this backend was selected (explicit | follow-on | workload-default | global-default | auto:<weight/candidate summary>)",
  "attempt": "int",
  "providerDetail": {
    "discriminator": "'batch' | 'azure_ml' | 'local'",
    "batch": { "jobId": "string", "taskId": "string" },
    "azureMl": { "jobName": "string", "workspace": "string" },
    "local": { "executionDirectory": "string", "processId": "int | null" }
  }
}
```

**Never persisted:** access tokens, account keys, SAS tokens, raw
credentials, or full signed input URLs. `MetadataUtils` generates
`executionId` and timestamps consistently with existing HASTE ID/timestamp
conventions.

#### Capacity and error models

- `ComputeResources` — shared shape used by both `ComputeJobSpec.resources`
  and `get_capacity()`.
- `CapacitySnapshot` — `{backend, workload, state: CapacityState,
  observedAt, detail}`; short-lived and advisory, never authoritative over
  the provider's own scheduler.
- Typed exceptions (all raised by adapters, caught by
  `ComputeExecutionService`): `BackendConfigurationError`,
  `BackendUnavailableError`, `CapacityUnavailableError`,
  `SubmissionIndeterminateError`, `JobNotFoundError`,
  `OutputNotAvailableError`, `JobCancellationError`.

### Modified module: `hastegeo.core.models.projects`

| Model | Field | Before | After | Notes |
|---|---|---|---|---|
| `TrainingJob` | `computeJob` | did not exist | `Optional[ComputeJobHandle] = None` | `jobId`/`taskId` retained; both populated on new submissions during the compatibility window |
| `InferenceJob` | `computeJob` | did not exist | `Optional[ComputeJobHandle] = None` | same |
| `ImageryPreprocessJob` | `computeJob` | did not exist | `Optional[ComputeJobHandle] = None` | same |
| `ZipJob` | `computeJob` | did not exist | `Optional[ComputeJobHandle] = None` | same |

**Legacy compatibility:** when `computeJob` is absent but `jobId`/`taskId` are
present, HASTE synthesizes a Batch `ComputeJobHandle`
(`selectedBackend=azure_batch`, `providerDetail.batch={jobId, taskId}`,
`routingReason="legacy-synthesized"`) at read time. No migration/backfill of
existing Cosmos documents is required; this is a compatible additive field, so
no `type` discriminator or document version bump is needed. Client-supplied
`computeJob` values on API requests are rejected — the field is
server-populated only.

## Configuration Changes (`hastegeo.core.config`)

New typed configuration alongside — not replacing — the existing Batch config
model:

| Config Key | Type | Default | Description |
|---|---|---|---|
| `COMPUTE_BACKEND_DEFAULT` | `ComputeBackend` | `azure_batch` | Global fallback backend |
| `COMPUTE_BACKEND_TRAINING` | `ComputeBackend` \| unset | unset | Per-workload override |
| `COMPUTE_BACKEND_INFERENCE` | `ComputeBackend` \| unset | unset | Per-workload override |
| `COMPUTE_BACKEND_EMBEDDING` | `ComputeBackend` \| unset | unset | Per-workload override |
| `COMPUTE_BACKEND_IMAGERYPREP` | `ComputeBackend` \| unset | unset | Per-workload override |
| `COMPUTE_BACKEND_ARTIFACTS` | `ComputeBackend` \| unset | unset | Per-workload override |
| `COMPUTE_AUTO_CANDIDATES_<WORKLOAD>` | comma-separated `ComputeBackend` | unset | Backends `auto` may select for a workload |
| `COMPUTE_AUTO_WEIGHTS_<WORKLOAD>` | comma-separated ints | unset (equal) | Rendezvous-hash weights |
| `COMPUTE_FOLLOW_ON_INHERITS_BACKEND` | bool | `true` | Automatic follow-ons reuse the originating backend when supported |
| `RUNNER_TYPE` | string | — | Deprecated alias for `COMPUTE_BACKEND_DEFAULT` |
| `AML_MODE` | `Disabled` \| `Create` \| `Existing` | `Disabled` | AML resource ownership mode. Stage 1 rollout uses `Existing`: a pure reference to an operator-provided workspace/compute/environment/datastore/identity — no resource creation, no RBAC assignment. `Create` compiles locally and is available in source for a separately approved future scenario, but is not applied this rollout |
| `AML_SUBSCRIPTION_ID` | string | unset unless `AML_MODE != Disabled` | AML subscription |
| `AML_RESOURCE_GROUP` | string | unset unless `AML_MODE != Disabled` | AML resource group |
| `AML_WORKSPACE_NAME` | string | unset unless `AML_MODE != Disabled` | AML workspace |
| `AML_DATASTORE_NAME` | string | unset unless `AML_MODE != Disabled` | Registered HASTE storage datastore |
| `AML_COMPUTE_<WORKLOAD>` | string | unset unless workload uses AML | Compute cluster name per workload tier |
| `AML_ENVIRONMENT_<IMAGE>` | string | unset unless workload uses AML | Immutable environment version per workload image |
| `AML_IDENTITY_MODE` | `user` \| `managed` | `user` | Identity AML jobs submit/authenticate as. `user` (default) maps to AML's `UserIdentityConfiguration` — the job runs as the *submitting principal's own identity* (the calling Function App's identity); needs no extra AML-specific grant beyond whatever access that identity already holds. `managed` maps to `ManagedIdentityConfiguration`, using `AML_MANAGED_IDENTITY_ID`. |
| `AML_MANAGED_IDENTITY_ID` | string | unset | User-assigned managed identity resource ID; required only when `AML_IDENTITY_MODE=managed`, ignored otherwise |
| `AML_EXPERIMENT_PREFIX` | string | `haste` | AML experiment naming prefix |
| `AML_SUBMISSION_TIMEOUT_SECONDS` | int | provider-appropriate default | Bounded provider call timeout |

Validation is conditional: `AML_*` settings are only required/validated when
`AML_MODE != Disabled` or a job explicitly requests `azure_ml`. A Batch-only
deployment does not import or initialize the `azure-ai-ml` SDK. `AML_MODE`
being `Disabled` (default) means HASTE creates no AML resource; it does not
mean the `AML_*` settings are absent from the Function App's configuration —
the IaC unconditionally emits every `AML_*` key with an inert/empty value
(e.g. `AML_MODE=Disabled`) rather than omitting the key (see
[design.md](design.md#infrastructure)).

## Blob Storage / Data Lake

No new containers, no new path conventions. Outputs continue to land under
the existing `{project-hash}/{task-id}/...` prefix regardless of backend;
`ComputeJobHandle.outputUri` records this same prefix rather than introducing
a new one.

## Queue Storage

No new queues and no message-schema change. Existing queue messages continue
to carry complete `Model`, `ImageLayer`, or `ModelArtifacts` records; the
compute backend selection travels as part of the referenced job record
(`computeJob.requestedBackend`), not as new queue-message fields.

## Azure Batch Changes

None beyond what `batch-compute-expansion` already defines. This feature adds
an adapter boundary around the existing Batch behavior; pool topology,
routing, and SAS behavior are unchanged.

## Azure Machine Learning Changes (new)

| Setting | Value | Notes |
|---|---|---|
| Workspace | reference an operator-provided workspace (`Existing`, used in Stage 1) or create one (`Create`, not applied this rollout) | No account keys; keyless auth only. `Existing` performs no resource creation and no RBAC assignment — HASTE only reads app-setting references to the operator-provided workspace |
| Compute clusters | reference operator-provided compute target names (`Existing`) or create one per workload tier (`Create`, not applied) | `Create` would use `min_instances=0`, bounded `max_instances`; `Existing` assumes the operator's compute already exists and is sized appropriately |
| Environments | reference operator-provided environment versions (`Existing`) or register an immutable version per HASTE image reference (`Create`, not applied) | `Create` would register from the same container image tag/digest Batch uses |
| Datastore | reference an operator-provided datastore name (`Existing`) or register the HASTE storage account as a new datastore via identity-based access (`Create`, not applied) | No account key in either mode |
| RBAC | none in `Existing` — granting the identity HASTE runs as access to the referenced resources is the operator's responsibility, outside HASTE's IaC | `Create` (not applied) would deploy `amlRole.bicep`, granting the built-in *AzureML Data Scientist* role (submit/read/cancel jobs, read compute) to the queue Function App's identity |

## Data Flow

### Write path (unchanged shape, backend-neutral source)

```
UI → hastefuncapi → Cosmos DB (job record incl. requestedBackend)
                  → Queue Storage (existing message schema)
                  → hastefuncqueues → hastegeo processor
                                    → ComputeExecutionService.submit()
                                    → Cosmos DB (persisted computeJob handle)
                                    → Blob Storage / Data Lake (artifacts, backend-independent path)
                                    → Azure Batch or Azure ML (compute)
```

### Read path (unchanged)

```
UI → hastefuncapi → Cosmos DB (metadata incl. computeJob / legacy jobId+taskId)
                  → Blob Storage (artifacts, direct SAS URL)
UI → titilerfuncapi → Blob Storage (COG tiles)
```

## Migration Plan

### Forward migration

1. Deploy the `hastegeo.core.models.compute` module and the additive
   `computeJob` field — no Cosmos schema migration or backfill required
   (optional field, existing documents deserialize unchanged).
2. Deploy processors that populate both `computeJob` and legacy `jobId`/
   `taskId` on new submissions.
3. Ship AML IaC with `Disabled` as the default. Enable `Existing` mode (a
   pure reference to an operator-provided workspace/compute/environment/
   datastore/identity — no resource creation, no RBAC assignment) for the
   Stage 1 rollout. `Create` mode remains available in source for a
   separately approved future scenario and is not applied in this rollout.
4. Enable explicit `azure_ml` selection per workload per
   [rollout.md](rollout.md).

### Backward migration

1. Revert processors to the previous release; `jobId`/`taskId` remain
   authoritative and unaffected since they were never removed.
2. Cosmos documents: no rollback action needed — `computeJob` is ignored by
   old code, not required by it.
3. Blob artifacts: no cleanup needed — output paths did not change.
4. AML resources: set `AML_MODE=Disabled`. Because `Existing` mode never
   created or modified any AML resource, there is nothing for HASTE to
   decommission in this rollout. If a future, separately approved scenario
   applies `Create` mode, its resources would require their own separate
   decommissioning under that scenario's own retention requirements.

## Data Volume Estimates

No material volume change. `ComputeJobHandle` adds a small, bounded JSON
object (a few hundred bytes) to four existing document types; no new
documents, containers, or high-cardinality collections are introduced.

## Caching Strategy

| Data | Cache Layer | TTL | Invalidation |
|---|---|---|---|
| `CapacitySnapshot` | In-process, per adapter/profile | short (seconds, provider-appropriate) | time-based expiry only; never authoritative, so staleness is tolerated |
| AML `MLClient` / Batch SDK clients | In-process, per immutable backend profile | process lifetime | recreated on profile change, not on every job |
