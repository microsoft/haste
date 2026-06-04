# HASTE Architecture Overview

**Last updated:** 2026-04-27

## System Context

HASTE (High-speed Assessment and Satellite Tracking for Emergencies) is an AI-driven framework for rapid disaster assessment using satellite and remote sensing data. It automates geospatial analysis with machine learning to produce accurate disaster maps.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         React UI (Vite)                          │
│  Projects · Labeling Tool · Visualizer · Admin · Model Catalog   │
│  Tech: React, Fluent UI, Azure Maps, D3, Chart.js               │
│  Auth: MSAL (@azure/msal-react)                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP via SWA proxy
┌───────────────────────────▼─────────────────────────────────────┐
│               Azure Static Web Apps / SWA CLI                    │
└──────┬────────────────────────────────────────────┬─────────────┘
       │ /api/*                                     │ tile requests
┌──────▼──────────────┐                    ┌────────▼─────────────┐
│   hastefuncapi       │                    │   titilerfuncapi     │
│   (28 HTTP routes)   │                    │   (TiTiler/FastAPI)  │
│   Azure Functions    │                    │   COG tile serving   │
│   Python 3.11+       │                    │   Python             │
└──────┬──────────────┘                    └──────────────────────┘
       │ Queue messages
┌──────▼──────────────┐
│   hastefuncqueues    │
│   (6 queue triggers) │
│   Azure Functions    │
└──────┬──────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│                    hastegeo (core library)                        │
│  core/config · core/models · core/processors                     │
│  core/data_layer · core/runners · core/utils                     │
│  workflows/prepare_imagery · workflows/zip_artifacts             │
└──────┬───────────┬───────────┬───────────┬──────────────────────┘
       │           │           │           │
  ┌────▼───┐  ┌───▼────┐  ┌──▼───┐  ┌───▼──────────┐
  │ Blob   │  │ Cosmos │  │ Data │  │ Azure Batch  │
  │ Storage│  │ DB     │  │ Lake │  │ (GPU pools)  │
  └────────┘  └────────┘  └──────┘  └──────────────┘
```

## Components

### React UI (`ui/`)
- Vite build toolchain
- Fluent UI component library
- MSAL for Entra ID authentication
- Azure Maps for geospatial visualization
- Key pages: Projects, Labeling Tool, Visualizer, Admin, Model Catalog

### REST API — `hastefuncapi` (`api/hastefuncapi/`)
- Python Azure Functions (v4 programming model)
- 28 HTTP endpoints: projects, image layers, models, labels, users, admin, model catalog
- Auth: `func.AuthLevel.FUNCTION`

### Queue Workers — `hastefuncqueues` (`api/hastefuncqueues/`)
- Python Azure Functions with 6 queue-triggered functions
- Handles: imagery preprocessing, model training, inference, artifact management

### Tile Server — `titilerfuncapi` (`api/titilerfuncapi/`)
- TiTiler / FastAPI for serving Cloud-Optimized GeoTIFF (COG) tiles

### Core Library — `hastegeo` (`hastelib/src/hastegeo/`)
- `core/config.py` — Configuration management
- `core/models/` — Data models and schemas
- `core/processors/` — Imagery and data processing logic
- `core/data_layer/` — Cosmos DB, Blob Storage, Data Lake, Queue access
- `core/runners/` — Azure Batch job submission and management
- `core/utils/` — Shared utilities
- `core/artifact_storage/` — Model artifact management
- `workflows/` — Multi-step workflows (imagery preparation, artifact packaging)

## Data Flow

### Synchronous (API reads/writes)
`UI → SWA → hastefuncapi → Cosmos DB / Blob Storage → response`

### Asynchronous (processing jobs)
`UI → hastefuncapi → Queue Storage → hastefuncqueues → hastegeo → Azure Batch (GPU) → Blob Storage / Data Lake`

### Tile Serving
`UI → SWA → titilerfuncapi → Blob Storage (COG) → rendered tile`

## Infrastructure

### Azure Services
- **Compute:** Azure Functions (consumption), Azure Batch (GPU pools)
- **Storage:** Blob Storage, Data Lake Storage Gen2, Queue Storage
- **Database:** Cosmos DB
- **Hosting:** Azure Static Web Apps
- **Auth:** Entra ID (MSAL)
- **CI/CD:** GitHub Actions (deploy-apps, docker-build-and-push, docs-deploy, secret-scan)
- **Compliance:** Azure Pipelines (CredScan, PoliCheck, Component Governance)

## Agent Architecture

HASTE uses specialized Copilot agents (`.github/agents/`) with clear boundaries. Skills are preferred over agents where possible.

### Agent Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Human Reviewers                          │
│              (approve all merges & security fixes)           │
└──────┬──────────────────────────────────────────┬───────────┘
       │ reviews                                  │ reviews
┌──────▼──────────────┐                  ┌────────▼──────────┐
│  Orchestrator       │                  │  Security Agent   │
│  (PM / traceability)│                  │  (alerts, CVEs)   │
│  observes all ──────┼──────────────────│  read-only        │
└─────────────────────┘                  └────────┬──────────┘
                                                  │ validated by
┌─────────────────────────────────┐      ┌────────▼──────────┐
│  Core Dev Agents                │      │  Security         │
│  ┌───────────┐ ┌────────────┐  │      │  Validation Agent │
│  │ backend-  │ │  gis       │  │      └───────────────────┘
│  │ dev       │ │  (imagery) │  │
│  └─────┬─────┘ └─────┬──────┘  │
│        │              │         │
│  ┌─────▼──────────────▼──────┐  │
│  │      ui                   │  │
│  │      (React/FluentUI)     │  │
│  └───────────────────────────┘  │
└──────────────┬──────────────────┘
               │ validated by
┌──────────────▼──────────────────┐
│  Validation Agents              │
│  ┌────────────────┐ ┌────────┐  │
│  │ backend-       │ │ ui-    │  │
│  │ validation     │ │ valid. │  │
│  └────────────────┘ └────────┘  │
└─────────────────────────────────┘
```

### Core Agents

| Agent | File | Scope | Touches Code? |
|-------|------|-------|--------------|
| Backend Dev | `backend-dev.agent.md` | Python backend, API, processors, data layers, runners | Yes |
| GIS | `gis.agent.md` | Satellite imagery, GDAL/rasterio, provider adapters, damage assessment | Yes |
| UI | `ui.agent.md` | React/FluentUI/Azure Maps/MSAL, frontend only | Yes |
| Security | `security.agent.md` | Dependabot alerts, CVE analysis, dependency audits | No (reports only) |

### Validation Agents

| Agent | File | Validates | Method |
|-------|------|-----------|--------|
| Backend Validation | `backend-validation.agent.md` | Backend code against specs, conventions, tests | Runs `hatch run test:pytest`, reads code |
| UI Validation | `ui-validation.agent.md` | Frontend changes against expected behavior | Runs Playwright tests |
| Security Validation | `security-validation.agent.md` | Security Agent findings (packages real, CVEs accurate) | Web research, cross-reference |

### Support Agent

| Agent | File | Purpose |
|-------|------|---------|
| Orchestrator | `orchestrator.agent.md` | Records what agents did, when, why. Run logs, summaries. |

### Skills (`.github/skills/`)

| Skill | Domain | Used By |
|-------|--------|---------|
| `security-analysis` | Dependabot triage, CVE analysis | Security, Security Validation |
| `imagery-provider-adaptation` | Satellite provider adapters | GIS, Backend Dev |
| `deterministic-scripts` | Exact build/deploy commands | Backend Dev, GIS, Backend Validation |
| `validation-diagnostics` | Planned vs implemented comparison | All validation agents |
| `api-design` | REST API conventions | Backend Dev, GIS |
| `debug-test-failures` | Test failure diagnosis | Backend Dev, GIS, UI |
| `dependency-update` | Safe dependency upgrades | Backend Dev, Security |
| `release-notes` | Changelog generation | Orchestrator |
| `copilot-cli-modes` | CLI workflow modes | All agents |

### Guardrails

- **No auto-merge** of security fixes — humans remain in the approval loop
- **No monolithic agents** — use specialized agents and skills
- **Skills preferred over agents** where possible
- Agents must never claim tests ran without observable evidence
- Agents read specs before implementing — check `spec/features/` for relevant design docs

## Specification System

All feature work, refactors, and architecture decisions are driven by specs in `spec/`.

### Spec Structure

```
spec/
├── architecture/
│   ├── overview.md              # This file — system architecture
│   └── decisions/               # ADRs: 0001-template.md, 0002-xyz.md
├── features/                    # One subfolder per feature spec
│   └── <feature-name>/
│       ├── README.md            # Overview, status, components affected
│       ├── plan.md              # Execution plan, phases, milestones
│       ├── impact-analysis.md   # Risk, dependencies, blast radius
│       ├── user-stories.md      # User stories & acceptance criteria
│       ├── design.md            # Technical design & API contracts
│       ├── data-model.md        # Cosmos DB / Blob / Data Lake schema changes
│       ├── test-plan.md         # Test strategy & coverage matrix
│       └── rollout.md           # Rollout strategy, flags, rollback
└── _templates/                  # Copy templates when starting new work
```

### Spec ↔ Agent Integration

1. **Dev agents** (backend-dev, gis, ui) read specs before implementing.
2. **Validation agents** compare implementations against spec acceptance criteria.
3. **Orchestrator** tracks spec status and updates `plan.md` after work.
4. **Architecture changes** require an ADR in `spec/architecture/decisions/`.
5. **Status lifecycle**: `draft` → `in-review` → `approved` → `in-progress` → `implemented` → `released`

### Architecture Decision Records (ADRs)

ADRs are stored in `spec/architecture/decisions/` using sequential numbering (`0001-template.md`, `0002-xyz.md`). Use the template at `0001-template.md` for new decisions.

When to create an ADR:
- New Azure service introduced
- Storage schema changes (Cosmos, Blob, Data Lake)
- New imagery provider integration architecture
- Authentication or authorization changes
- CI/CD pipeline structural changes
- Agent architecture changes

### Local Development
- Docker Compose stack (`docker/docker-compose.yml`)
- Azurite storage emulator
- SWA CLI for UI development
- Conda environment (`env.yml`, `env_build.yml`)

### Deployment Environments
| Env | Method | Auth |
|---|---|---|
| Local | `docker-compose up` | None (DEVELOPMENT_MODE=true) |
| Dev1 | SWA CLI | MSAL |
| Testing | SWA CLI | MSAL |
| Production | GitHub Actions OIDC (`fed-cred-main.json`) | MSAL + Function keys |
