# HASTE — Repository-Wide Copilot Instructions
#
# These instructions are automatically loaded into EVERY Copilot session
# (VS Code, Copilot CLI, Cloud Agent, Code Review).
# Keep them concise and universally applicable.

## Project Overview

- **Name**: HASTE (High-speed Assessment and Satellite Tracking for Emergencies)
- **Description**: AI-driven framework for rapid disaster assessment using satellite and remote sensing data
- **Primary Languages**: Python 3.11 (backend/core), JavaScript/React (UI)
- **Package Managers**: pip/conda (Python), npm (UI)
- **Owner**: microsoft/haste

## Architecture

```
React UI (Vite + FluentUI + Azure Maps + MSAL)
  └─ Azure Static Web Apps / SWA CLI
       ├─ hastefuncapi (41 HTTP routes, Azure Functions, Python)
       ├─ titilerfuncapi (TiTiler/FastAPI, COG tile serving)
       └─ hastefuncqueues (7 queue triggers, Azure Functions, Python)
            └─ hastegeo core library (hastelib/)
                 ├─ Config · Models · Processors · Data Layers
                 ├─ Runners (Azure Batch GPU) · Utils · Workflows
                 └─ Storage: Blob, Cosmos DB, Data Lake, PostgreSQL
```

## Build & Test

- **Core library build**: `cd hastelib && hatch build -t wheel`
- **Core library tests**: `cd hastelib && hatch run test:pytest`
- **Core library tests (specific file)**: `cd hastelib && hatch run test:pytest tests/path/to/test_file.py -v`
- **UI build**: `cd ui && npm run build`
- **UI lint**: `cd ui && npm run lint`
- **API local run**: `cd api/hastefuncapi && func host start`
- **UI local run**: `cd ui && swa start --app-devserver-url http://localhost:5173 --run 'npm run dev'`

Always run tests before marking a task as complete.
Always run lint before committing changes.

## Coding Standards

### Python (backend, core library)
- Python 3.11+. Use type hints everywhere.
- Pydantic models for data validation (already used throughout).
- Follow existing patterns in `hastegeo.core.processors` for business logic.
- Follow existing patterns in `hastegeo.core.data_layer` for storage backends.
- GDAL/rasterio for geospatial operations — never use raw file I/O for imagery.
- Never hardcode Azure connection strings or keys. Use `Config` class from `hastegeo.core.config`.

### JavaScript/React (UI)
- React functional components with hooks.
- FluentUI component library — do not introduce alternative UI frameworks.
- Azure Maps for all geospatial visualization — no Leaflet/Mapbox.
- MSAL for authentication — do not bypass or mock in production paths.

### General
- Write clear, self-documenting code. Avoid unnecessary comments.
- Prefer small, focused functions over long procedural blocks.
- Handle errors explicitly — do not silently swallow exceptions.
- Validate inputs at system boundaries; trust internal data.
- Never commit secrets, credentials, or API keys.

## Key Domain Concepts

- **Project**: A disaster assessment campaign (e.g., "Maui Wildfires 2023")
- **Image Layer**: A set of pre/post-event satellite imagery for a project
- **Source Type**: Satellite imagery provider (Planet, Vantor, Airbus, etc.)
- **Label Project**: Human labeling of damage on imagery tiles
- **Model**: ML model trained on labeled data for damage classification
- **Inference**: Running a trained model on new imagery
- **Artifact**: Model weights, predictions, and outputs
- **COG**: Cloud Optimized GeoTIFF — the standard imagery format

## Git Conventions

- Default branch: `main`
- Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`
- Keep PRs focused — one logical change per PR.
- Write descriptive PR titles and descriptions.

## Specification System

All feature work, refactors, and architecture decisions are driven by specs in `spec/`.

### Structure

```
spec/
├── architecture/
│   ├── overview.md              # System architecture (canonical reference)
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
    ├── feature/                 # Full feature spec template
    └── modification/            # Lighter template for refactors/migrations
```

### Spec Workflow

1. **Before implementing**: Check `spec/features/` for the relevant spec. Read the `design.md` and `user-stories.md` first.
2. **During implementation**: Validate work against the spec's acceptance criteria. Update `plan.md` status as tasks complete.
3. **Architecture decisions**: Record in `spec/architecture/decisions/` using the ADR template.
4. **New features**: Copy `spec/_templates/feature/` to `spec/features/<name>/` and fill in docs before coding.
5. **Status lifecycle**: `draft` → `in-review` → `approved` → `in-progress` → `implemented` → `released`

### Rules

- Never start feature work without a spec (at minimum `README.md` + `design.md`).
- Architecture changes require an ADR in `spec/architecture/decisions/`.
- Specs are the source of truth — if code diverges from spec, update the spec or fix the code.
- Cross-reference related specs using relative paths.

## Agent Architecture

HASTE uses specialized agents with clear boundaries. Skills are preferred over agents where possible.

### Core Agents

| Agent | Scope | Touches Code? |
|-------|-------|--------------|
| `backend-dev` | Python backend, API, processors, data layers, runners | Yes |
| `gis` | Satellite imagery, GDAL/rasterio, provider adapters, damage assessment | Yes |
| `ui` | React/FluentUI/Azure Maps/MSAL, frontend only | Yes |
| `security` | Dependabot alerts, CVE analysis, dependency audits. Never auto-merges. | No (reports only) |

### Validation Agents

| Agent | Validates | Method |
|-------|-----------|--------|
| `backend-validation` | Backend code against specs, conventions, tests | Runs `hatch run test:pytest`, reads code |
| `ui-validation` | Frontend changes against expected behavior | Runs Playwright tests |
| `security-validation` | Security Agent findings (packages real, CVEs accurate) | Web research, cross-reference |

### Support Agent

| Agent | Purpose |
|-------|---------|
| `orchestrator` | Records what agents did, when, why. Run logs, summaries. Does not own execution. |

### Agent ↔ Spec Integration

- Agents **read specs before implementing** — check `spec/features/` for relevant design docs.
- Validation agents **compare implementations against spec acceptance criteria**.
- The orchestrator **tracks spec status** and updates `plan.md` after agent work.
- Architecture changes trigger an **ADR in `spec/architecture/decisions/`**.

### Agent ↔ Story Mapping (Required)

Every feature spec **must** map user stories to HASTE agents. This is enforced in the templates:

- **`user-stories.md`** must include an **Agent Assignment Map** table: story → implementing agent + validating agent.
- **`plan.md`** must use agent names (not people/roles) in the **Agent** column of task tables.
- **Assignment rules:**
  - `hastelib/`, `api/`, `docker/`, `.github/workflows/` → `backend-dev` implements, `backend-validation` validates.
  - Satellite imagery, GDAL, provider adapters → `gis` implements or co-implements.
  - `ui/` → `ui` implements, `ui-validation` validates.
  - New dependencies → `security` audits, `security-validation` confirms.
  - `orchestrator` tracks all work — does not need per-story assignment.

## Guardrails

- **No auto-merge** of security fixes — humans remain in the approval loop.
- **No monolithic agents** — use specialized agents and skills.
- **Skills preferred over agents** where possible.
- Agents must never claim tests ran without observable evidence.

## Communication

- Be concise. Explain tradeoffs briefly, then provide the recommended choice.
- When multiple approaches exist, present the best option with a one-line justification.
- If unsure about intent, ask a clarifying question rather than guessing.
