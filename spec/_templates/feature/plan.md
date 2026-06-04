# Execution Plan: [Feature Title]

## Phases

### Phase 1: Core Library — [target date]

**Goal:** Implement core logic in `hastelib/src/hastegeo/`.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add/modify data models in `hastegeo/core/models/` | `backend-dev` | — | US-xxx | not-started |
| Implement processors in `hastegeo/core/processors/` | `backend-dev` | — | US-xxx | not-started |
| Add data layer access in `hastegeo/core/data_layer/` | `backend-dev` | — | US-xxx | not-started |
| Write unit tests in `hastelib/tests/` | `backend-dev` | All above | US-xxx | not-started |

> **Agent column:** Use HASTE agent names (`backend-dev`, `gis`, `ui`, `security`). See [user-stories.md](user-stories.md#agent-assignment-map) for the full agent→story mapping.

**Exit Criteria:**
- [ ] All unit tests pass
- [ ] Core logic works independently of API layer

### Phase 2: API Layer — [target date]

**Goal:** Expose feature via `hastefuncapi` HTTP routes and/or `hastefuncqueues` triggers.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add HTTP endpoints to `api/hastefuncapi/function_app.py` | `backend-dev` | Phase 1 | US-xxx | not-started |
| Add queue triggers to `api/hastefuncqueues/function_app.py` (if async) | `backend-dev` | Phase 1 | US-xxx | not-started |
| Update `requirements.txt` if new dependencies | `backend-dev` | — | — | not-started |
| Update Docker images if needed (`docker/api/`, `Dockerfile`) | `backend-dev` | — | — | not-started |

**Exit Criteria:**
- [ ] Endpoints callable via REST
- [ ] Queue processing works end-to-end
- [ ] Works in Docker Compose local stack

### Phase 3: UI — [target date]

**Goal:** Surface feature in React UI.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| Add/modify React components in `ui/src/Components/` | `ui` | Phase 2 | US-xxx | not-started |
| Wire API calls via `AppHelper.js` or new util | `ui` | Phase 2 | US-xxx | not-started |
| Update navigation / routing if new page | `ui` | — | — | not-started |

**Exit Criteria:**
- [ ] Feature accessible from UI
- [ ] Works with SWA CLI local dev (`swa start`)

### Phase 4: Integration & Deployment — [target date]

**Goal:** Validate end-to-end and deploy.

| Task | Agent | Dependencies | Story Ref | Status |
|---|---|---|---|---|
| End-to-end testing with Docker Compose | `backend-dev` | Phase 3 | — | not-started |
| Update `docker-compose.yml` if new services | `backend-dev` | — | — | not-started |
| Update GitHub Actions workflows if needed | `backend-dev` | — | — | not-started |
| Update docs in `docs/` | `backend-dev` | — | — | not-started |

**Exit Criteria:**
- [ ] `docker-compose up` starts clean with feature working
- [ ] CI pipeline passes (secret-scan, deploy-apps)
- [ ] Docs updated

## Milestones

| Milestone | Date | Deliverable |
|---|---|---|
| Spec approved | | Signed-off design docs |
| Core library done | | `hastelib` changes merged |
| API layer done | | Endpoints/queues functional |
| UI done | | Feature visible in React app |
| Release | | Deployed to production SWA |

## Agent Summary

| Agent | Tasks Owned | Phases |
|---|---|---|
| `backend-dev` | [count] | 1, 2, 4 |
| `gis` | [count] | [phases] |
| `ui` | [count] | 3 |
| `security` | [count] | [phases] |

> Populate from the task tables above. Every task must have an agent.

## Resource Requirements

- **Agents:** [which HASTE agents are needed — see user-stories.md agent assignment]
- **Azure services:** [any new services: Batch pools, storage containers, Cosmos collections]
- **GPU compute:** [if model training/inference is involved — specify pool size, VM SKU]
- **External data:** [imagery sources, partner APIs]

## Open Questions

- [ ] Unresolved planning items.
