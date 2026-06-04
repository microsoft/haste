# HASTE Specifications

This directory contains all feature specs, modification proposals, and architecture decisions for the HASTE platform (High-speed Assessment and Satellite Tracking for Emergencies).

## Codebase Reference

| Component | Path | Tech | Description |
|---|---|---|---|
| **Core Library** | `hastelib/src/hastegeo/` | Python 3.11+ | Config, models, processors, data layers, runners, utils |
| **REST API** | `api/hastefuncapi/` | Python Azure Functions | 28 HTTP routes (projects, image layers, models, labels, users, admin) |
| **Queue Workers** | `api/hastefuncqueues/` | Python Azure Functions | 6 queue triggers for long-running ops (imagery prep, training, inference) |
| **Tile Server** | `api/titilerfuncapi/` | TiTiler / FastAPI | COG tile serving |
| **UI** | `ui/src/` | React / Vite / Fluent UI | Projects, Labeling Tool, Visualizer, Admin, Model Catalog |
| **Docker Dev** | `docker/` | Docker Compose | Full local stack with Azurite emulator |
| **Infra / CI** | `.github/workflows/` | GitHub Actions | deploy-apps, docker-build-and-push, docs-deploy, secret-scan |
| **Compliance CI** | `azure-pipelines.yml` | Azure Pipelines | CredScan, PoliCheck, Component Governance |

## Azure Services

| Service | Purpose |
|---|---|
| Azure Static Web Apps | Host React UI + API routing |
| Azure Functions | REST API + queue workers |
| Cosmos DB | Project metadata, user data, model configs |
| Blob Storage | Imagery, model artifacts, labels |
| Data Lake Storage | Large geospatial datasets |
| Azure Batch (GPU pools) | Model training and inference |
| Queue Storage | Async job orchestration |
| MSAL / Entra ID | Authentication |

## Structure

```
spec/
├── _templates/
│   ├── feature/                       # Copy this folder for each new feature
│   │   ├── README.md                  # Feature overview & status tracker
│   │   ├── plan.md                    # Execution plan, milestones, phases
│   │   ├── impact-analysis.md         # Risk, dependencies, blast radius
│   │   ├── user-stories.md            # User stories & acceptance criteria
│   │   ├── design.md                  # Technical design & API contracts
│   │   ├── data-model.md              # Cosmos DB / Blob / Data Lake schema changes
│   │   ├── test-plan.md               # Test strategy & coverage matrix
│   │   └── rollout.md                 # SWA environment rollout, feature flags, rollback
│   └── modification/                  # Copy this folder for refactors/migrations
│       ├── README.md
│       ├── impact-analysis.md
│       └── plan.md
├── architecture/
│   ├── overview.md                    # HASTE system architecture
│   └── decisions/
│       └── 0001-template.md           # ADR template
├── features/                          # One subfolder per feature
└── modifications/
    ├── refactors/
    └── migrations/
```

## Workflow

1. Copy `_templates/feature/` or `_templates/modification/` into the target directory
2. Rename the folder with kebab-case: `features/multi-class-labeling/`
3. Fill in each file — start with `README.md`, then `user-stories.md`, then `design.md`
4. Update status in `README.md` as the feature progresses
5. ADRs use sequential numbering: `0001-switch-to-cosmos-nosql.md`
6. Cross-reference related specs using relative paths

## Status Lifecycle

`draft` → `in-review` → `approved` → `in-progress` → `implemented` → `released` | `deprecated`

## Agent Integration

HASTE uses specialized Copilot agents (`.github/agents/`) that are wired into the spec system. See `spec/architecture/overview.md` for the full agent architecture.

### How Agents Use Specs

| Agent | Spec Interaction |
|---|---|
| `backend-dev` | Reads `design.md` + `user-stories.md` before implementing. Updates `plan.md` status. |
| `gis` | Reads `design.md` for imagery provider requirements. Creates specs for new providers. |
| `ui` | Reads `user-stories.md` for acceptance criteria. Starts Phase 3 after Phases 1-2 complete. |
| `security` | References `impact-analysis.md` Security Impact section. Creates ADRs for security arch changes. |
| `backend-validation` | Compares implementation against `user-stories.md` acceptance criteria and `test-plan.md`. |
| `ui-validation` | Validates UI behavior against `user-stories.md` and `test-plan.md` UI scenarios. |
| `orchestrator` | Tracks `plan.md` status across all feature specs. Reports drift and stale specs. |

### Rules

- Never start feature work without a spec (at minimum `README.md` + `design.md`).
- Architecture changes require an ADR in `spec/architecture/decisions/`.
- Specs are the source of truth — if code diverges from spec, update the spec or fix the code.
- Validation agents compare implementations against spec acceptance criteria.

## Environments

| Environment | Config | Notes |
|---|---|---|
| `local` | `docker-compose -f docker/docker-compose.yml up` | Azurite emulator, no auth, DEVELOPMENT_MODE=true |
| `dev1` | `swa-cli.config.json → dev1` | Dev Azure subscription |
| `testing` | `swa-cli.config.json → test` | Test Azure subscription |
| `production` | GitHub Actions `deploy-apps.yml` | Prod — federated creds via `fed-cred-main.json` |
