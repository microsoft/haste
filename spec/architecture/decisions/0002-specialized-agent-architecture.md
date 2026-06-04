# ADR-0002: Specialized Agent Architecture for HASTE

**Status:** accepted
**Date:** 2026-04-27
**Deciders:** HASTE engineering team

## Context

HASTE needs AI agent assistance for development, security, and validation work. The question is whether to use a single monolithic agent or specialized agents with clear boundaries.

Key considerations:
- HASTE has distinct domains: backend Python, geospatial/imagery, React UI, security
- Geospatial processing requires deep domain knowledge (GDAL, rasterio, COG, CRS, satellite providers)
- Security fixes must never be auto-merged — humans remain in the approval loop
- Agents can claim tests passed when they didn't — validation must be independently verifiable
- Frontend and backend should be isolated to prevent cross-contamination

## Options Considered

### Option A: Single Monolithic Agent

- **Pros:** Simple setup, single context window, no coordination overhead
- **Cons:** Too broad — dilutes focus, mixes backend/frontend/security concerns, no validation independence
- **Impact on HASTE components:** All components mixed in one agent's context

### Option B: Specialized Agents with Skills (Chosen)

- **Pros:** Clear boundaries, domain expertise, independent validation, skills reusable across agents
- **Cons:** Coordination overhead, more files to maintain
- **Impact on HASTE components:** Each agent owns specific components, skills shared across agents

## Decision

Use specialized agents organized by domain, with portable skills for cross-cutting concerns. The architecture is:

**Core Agents (touch code):**
- `backend-dev` — Python backend, API, processors, data layers, runners
- `gis` — Satellite imagery, GDAL/rasterio, provider adapters, damage assessment
- `ui` — React/FluentUI/Azure Maps/MSAL, frontend only
- `security` — Dependabot alerts, CVE analysis, dependency audits (read-only, never auto-merges)

**Validation Agents (verify work):**
- `backend-validation` — Validates backend code against specs, runs tests
- `ui-validation` — Validates frontend with Playwright
- `security-validation` — Validates Security Agent findings

**Support Agent:**
- `orchestrator` — Lightweight PM, records what happened, tracks spec status

**Skills (portable units):**
- `security-analysis` — Dependabot triage, CVE analysis
- `imagery-provider-adaptation` — Satellite provider adapters
- `deterministic-scripts` — Exact build/deploy/test commands
- `validation-diagnostics` — Planned vs implemented comparison

### Components Affected

| Component | Path | Change |
|---|---|---|
| Agents | `.github/agents/` | 8 new agent files |
| Skills | `.github/skills/` | 4 new HASTE-specific skills |
| Instructions | `.github/instructions/` | 3 new domain-specific instructions |
| Copilot Instructions | `.github/copilot-instructions.md` | Added spec system and agent architecture |
| Architecture Overview | `spec/architecture/overview.md` | Added agent architecture and spec integration |

### Azure Services Affected

| Service | Change |
|---|---|
| None | Agent architecture is a development tooling decision, no runtime impact |

## Consequences

- **Easier:** Clear ownership of code areas, independent validation, security isolation
- **Harder:** Coordination between agents on cross-cutting features
- **New constraints:** All feature work requires a spec before implementation
- **Impact on Docker Compose local dev stack:** None
- **Impact on CI/CD workflows:** None (agents are development tooling)
