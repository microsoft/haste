# User Stories: Image Layer and Model Run Loading Performance

## Contents

- [Personas](#personas)
- [Stories](#stories)
- [Agent Assignment Map](#agent-assignment-map)
- [Story Map](#story-map)
- [Out of Scope](#out-of-scope)

## Personas

| Persona | Description | Key Goal |
|---|---|---|
| Disaster Analyst | Reviews imagery layers and model results during response work | Open and refresh large projects without long blocking waits |
| ML Engineer | Monitors training, embedding, and inference runs | Receive current run status without duplicate requests |
| Operator | Runs HASTE on supported metadata backends | Bound resource use and diagnose storage cost accurately |

## Stories

### US-001: Load Large Projects Reliably

**As a** disaster analyst, **I want** project layers and model runs loaded without
sequential N+1 storage waits, **so that** large assessments remain usable.

**Priority:** P0  
**Components:** `hastefuncapi`, `hastelib`

**Acceptance Criteria:**

```gherkin
Given a project with 50 layers and 5 models per layer
When GetProjectDetails is requested with includeModels=true
Then the response contains the same layers, models, artifacts, counts, and ordering as the legacy endpoint
And the request uses seven logical data-layer operations
```

```gherkin
Given legacy artifact or validation documents without embedded join IDs
When project details are assembled
Then related records are joined by their storage identifiers
```

### US-002: Bound Backend Concurrency

**As an** operator, **I want** concurrent metadata downloads to share one bounded
worker budget, **so that** requests cannot multiply thread usage without limit.

**Priority:** P0  
**Components:** `hastelib`

**Acceptance Criteria:**

```gherkin
Given multiple concurrent storage map operations
When they execute in one Functions worker process
Then aggregate blocking I/O never exceeds HASTE_BLOB_DOWNLOAD_WORKERS
And invalid worker settings fail fast
```

### US-003: Refresh Without Duplicate Work

**As an** ML engineer, **I want** project refreshes deduplicated and conditional,
**so that** polling does not pile up while jobs run.

**Priority:** P0  
**Components:** `hastefuncapi`, `ui/src`

**Acceptance Criteria:**

```gherkin
Given two concurrent requests for the same project response
When the first request is still loading
Then the API and UI each share one in-flight operation
```

```gherkin
Given an unchanged fresh cached response
When the UI sends its ETag
Then the API returns 304 without storage work
And the UI does not update project state
```

```gherkin
Given a project with no active jobs or a hidden browser tab
When the poll interval elapses
Then no project-details request is started
```

### US-004: Preserve Backend Compatibility

**As an** operator, **I want** the read contract consistent across configured metadata
backends, **so that** an optimization does not silently make Blob the only working path.

**Priority:** P1  
**Components:** `hastelib`

**Acceptance Criteria:**

```gherkin
Given Blob, local filesystem, Cosmos DB, Data Lake, or PostgreSQL metadata storage
When project-related read primitives are called
Then each backend accepts the shared read signatures
And unsupported remote label URLs degrade to null rather than fail the project
```

## Agent Assignment Map

| Story | Implementing Agent | Validating Agent | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | Golden response and local-storage regression |
| US-002 | `backend-dev` | `backend-validation` | Concurrency and failure-path tests |
| US-003 | `backend-dev`, `ui` | `backend-validation`, `ui-validation` | API cache plus browser request guards |
| US-004 | `backend-dev` | `backend-validation` | Mocked backend contract tests |

## Story Map

| Priority | Story | Phase | Component |
|---|---|---|---|
| P0 | US-001 | Backend hot path | `hastefuncapi`, `hastelib` |
| P0 | US-002 | Core library | `hastelib` |
| P0 | US-003 | Cache and UI polling | `hastefuncapi`, `ui/src` |
| P1 | US-004 | Backend compatibility | `hastelib` |

## Out of Scope

- A materialized per-project response document and write-side invalidation.
- Cross-instance distributed caching.
- Queue concurrency configuration changes without load testing.
- `summary` and `includeArtifacts` response modes.
- SignalR or another server-push transport.