# User stories: DINOv3-SAT building embeddings

## Stories

### US-001: Select DINOv3-SAT

**As a** disaster analyst, **I want to** select DINOv3-SAT for a building
embedding run, **so that** I can use satellite-pretrained features in the
Rapid Building Assessment workflow.

**Acceptance criteria:**

```gherkin
Given an image layer with processed imagery and building footprints
When I create an embedding and select DINOv3-SAT ViT-L/16
Then HASTE queues an embedding model with embeddingModel="dinov3_sat"
```

### US-002: Run without external model access

**As an** administrator, **I want to** stage the gated model once in managed
storage, **so that** Batch jobs run without internet access or Hugging Face
credentials.

**Acceptance criteria:**

```gherkin
Given an approved model snapshot in configured Blob Storage
When a DINOv3-SAT embedding job starts
Then the snapshot is staged into the task and loaded only from local files
```

```gherkin
Given the model Blob prefix is not configured
When a DINOv3-SAT embedding job is submitted
Then the model fails before Batch submission with a clear status message
```

### US-003: Reproduce model setup

**As an** ML engineer, **I want to** know the exact model, revision, files, and
configuration, **so that** I can reproduce or audit the deployment.

**Acceptance criteria:**

```gherkin
Given the DINOv3-SAT setup guide
When I follow its download, verification, upload, and configuration steps
Then HASTE can load the documented immutable snapshot
```

## Agent assignment map

| Story | Implementing agent(s) | Validating agent(s) |
|---|---|---|
| US-001 | `ui`, `backend-dev` | `ui-validation`, `backend-validation` |
| US-002 | `backend-dev`, `gis`, `security` | `backend-validation`, `security-validation` |
| US-003 | `backend-dev`, `orchestrator` | `backend-validation` |

## Out of scope

- Fine-tuning DINOv3-SAT inside HASTE.
- Runtime Hugging Face downloads.
- DINOv3 AnyUp and non-satellite model variants.

