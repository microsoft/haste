# User Stories: [Feature Title]

## Personas

| Persona | Description | Key Goals |
|---|---|---|
| Disaster Analyst | Domain expert who interprets satellite imagery and produces damage maps | Accurate, fast assessment results |
| ML Engineer | Builds and trains models for imagery classification | Efficient training workflows, model versioning |
| Project Manager | Oversees disaster response projects, manages team access | Project visibility, user management |
| Admin | Configures system settings, manages base models and source types | System configuration, model catalog |
| External Partner | Collaborator with limited access to specific projects | View results, provide labels |

> Keep only personas relevant to this feature.

---

## Stories

### US-001: [Story Title]

**As a** [persona],
**I want to** [action],
**So that** [benefit to disaster assessment workflow].

**Priority:** P0 | P1 | P2 | P3
**Estimate:** [points or t-shirt size]
**Component(s):** `hastefuncapi` / `ui/src/Components/...` / `hastelib` / ...

**Acceptance Criteria:**

```gherkin
Given [precondition — e.g. a project exists with uploaded imagery]
When [action — e.g. I click "Run Inference" on an image layer]
Then [expected result — e.g. a queue message is created and processing starts]
```

```gherkin
Given [error/edge case precondition]
When [action]
Then [expected error handling]
```

**UI Wireframe:** [link or description if applicable]

**Notes:** [edge cases, design references, related Components]

---

### US-002: [Story Title]

**As a** [persona],
**I want to** [action],
**So that** [benefit].

**Priority:** P0 | P1 | P2 | P3
**Estimate:** [points or t-shirt size]
**Component(s):** 

**Acceptance Criteria:**

```gherkin
Given [precondition]
When [action]
Then [expected result]
```

**Notes:**

---

### US-003: [Story Title]

**As a** [persona],
**I want to** [action],
**So that** [benefit].

**Priority:** P0 | P1 | P2 | P3
**Estimate:** [points or t-shirt size]
**Component(s):**

**Acceptance Criteria:**

```gherkin
Given [precondition]
When [action]
Then [expected result]
```

**Notes:**

---

## Agent Assignment Map

Every user story must be assigned to one or more HASTE agents. The **implementing agent** writes the code; the **validating agent** verifies correctness against acceptance criteria. See [Agent Architecture](../../architecture/overview.md#agent-architecture) for full agent descriptions.

### Available Agents

| Agent | Scope | Touches Code? |
|---|---|---|
| `backend-dev` | Python backend, API, processors, data layers, runners | Yes |
| `gis` | Satellite imagery, GDAL/rasterio, provider adapters, damage assessment | Yes |
| `ui` | React/FluentUI/Azure Maps/MSAL, frontend only | Yes |
| `security` | Dependabot alerts, CVE analysis, dependency audits | No (reports only) |
| `backend-validation` | Validates backend code against specs, conventions, tests | No (validates only) |
| `ui-validation` | Validates frontend changes against expected behavior | No (validates only) |
| `security-validation` | Validates security agent findings | No (validates only) |
| `orchestrator` | Records what agents did, when, why. Tracks spec status. | No (observes only) |

> Remove agents not involved in this feature.

### Story → Agent Mapping

| Story | Implementing Agent(s) | Validating Agent(s) | Notes |
|---|---|---|---|
| US-001 | `[agent]` | `[agent]` | |
| US-002 | `[agent]` | `[agent]` | |
| US-003 | `[agent]` | `[agent]` | |

> **Rules:**
> - Every story MUST have at least one implementing agent and one validating agent.
> - Stories touching `hastelib/`, `api/`, or `docker/` → `backend-dev` implements, `backend-validation` validates.
> - Stories touching satellite imagery, GDAL, or provider adapters → `gis` implements or co-implements.
> - Stories touching `ui/` → `ui` implements, `ui-validation` validates.
> - Stories adding new dependencies → `security` audits, `security-validation` confirms.
> - `orchestrator` tracks progress on all stories — no need to list per story.

### Agent Workflow Per Phase

| Phase | Lead Agent | Supporting Agents | Validation |
|---|---|---|---|
| Phase 1 — Core Library | `[agent]` | `[agents]` | `[agent]` |
| Phase 2 — API | `[agent]` | `[agents]` | `[agent]` |
| Phase 3 — UI | `[agent]` | `[agents]` | `[agent]` |
| Phase 4 — Integration | `[agent]` | `[agents]` | `[agent]` |

> Remove phases not applicable to this feature.

## Story Map

| Priority | Story | Phase | Implementing Agent | Component |
|---|---|---|---|---|
| P0 | US-001 | Phase 1 — Core Library | `[agent]` | `hastelib` |
| P1 | US-002 | Phase 2 — API | `[agent]` | `hastefuncapi` |
| P2 | US-003 | Phase 3 — UI | `[agent]` | `ui/src/Components/` |

## Out of Scope

Stories explicitly excluded from this feature:

- [ ] [Description — reason for exclusion]
