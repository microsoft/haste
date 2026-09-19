# User Stories: hastegeo CI build and release pipeline

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| HASTE contributor | Changes shared backend/library code | Fast, safe PR validation |
| HASTE maintainer | Reviews and publishes releases | Immutable, reproducible releases |
| HASTE operator | Deploys Function apps and Batch images | Exact wheel and image versions |

## Stories

### US-001: Build a release candidate safely

**As a** HASTE contributor,
**I want to** build an RC wheel without write credentials,
**So that** my PR can be validated without exposing the repository.

**Priority:** P0
**Component(s):** `hastelib`, `.github/workflows`

**Acceptance Criteria:**

```gherkin
Given a pull request changes hastelib
When the wheel build runs
Then the build job has read-only contents permission and no persisted Git credentials
And it uploads a validated RC wheel only as an Actions artifact
```

```gherkin
Given the PR is from a fork
When the workflow runs
Then it builds and tests but does not publish a wheel or image
```

### US-002: Publish immutable and idempotent wheels

**As a** HASTE maintainer,
**I want to** approve a trusted publisher,
**So that** RC and stable assets cannot overwrite prior releases.

**Priority:** P0
**Component(s):** `.github/scripts`, `.github/workflows`

**Acceptance Criteria:**

```gherkin
Given a validated artifact from a same-repository PR
When the trusted publisher runs
Then it accepts only an rcN filename whose METADATA and checksum match
And it fails if that asset already exists
```

```gherkin
Given a stable build is rerun for the same source SHA
When hastegeo-vX.Y.Z already points to that SHA
Then the workflow reuses or no-ops that version instead of incrementing
```

### US-003: Produce deployable version-coherent artifacts

**As a** HASTE operator,
**I want to** receive exact wheel and container image versions,
**So that** I can deploy the code reviewed in the PR.

**Priority:** P0
**Component(s):** `.github/workflows`, `docker`, `api`

**Acceptance Criteria:**

```gherkin
Given an RC wheel is published automatically
When image builds complete
Then training and imageryprep images use exactly that RC version as their tag
And the workflow summary contains their full ACR references
```

```gherkin
Given a nonexistent or invalid hastegeo version
When deployment is requested
Then it fails before any Azure resource is changed
```

### US-004: Review RC cleanup before deletion

**As a** HASTE maintainer,
**I want to** review cleanup candidates,
**So that** an RC still needed by an environment is not deleted automatically.

**Priority:** P1
**Component(s):** `.github/scripts`, `.github/workflows`

**Acceptance Criteria:**

```gherkin
Given the weekly cleanup schedule runs
When stale RCs are found
Then it reports candidates without deleting assets
```

```gherkin
Given a manual delete is approved
When the retain file is missing or keep is negative
Then the cleanup fails without deleting anything
```

## Agent Assignment Map

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `backend-dev` | `backend-validation` | Build hook and read-only workflow |
| US-002 | `backend-dev` | `backend-validation`, `security-validation` | Trusted publisher and tag policy |
| US-003 | `backend-dev` | `backend-validation` | ACR and Function deployment |
| US-004 | `backend-dev` | `backend-validation` | Report-first cleanup |

## Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Version/package core | `backend-dev` | `security` | `backend-validation` |
| CI/CD integration | `backend-dev` | `security` | `backend-validation`, `security-validation` |
| Deployment/cleanup | `backend-dev` | `orchestrator` | `backend-validation` |

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Build boundary | `backend-dev` | `hastelib`, Actions |
| P0 | US-002 | Publication | `backend-dev` | Releases, tags |
| P0 | US-003 | Deployment artifacts | `backend-dev` | ACR, Functions |
| P1 | US-004 | Cleanup | `backend-dev` | Releases |

## Out of Scope

- Moving wheels from GitHub Releases to a package registry.
- Automatic deletion during the first release cycle.
- Conventional-commit semantic version selection.
- New Azure resources or infrastructure changes.
