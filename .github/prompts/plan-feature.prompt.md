---
description: "Create a spec-driven implementation plan for a HASTE feature or change"
tools: ["read", "edit", "search", "web"]
argument-hint: "Describe the feature or change to plan"
---

Create a spec-driven implementation plan for the described feature or change.

## Instructions

1. Check if a spec already exists in `spec/features/` for this feature.
2. If no spec exists, copy `spec/_templates/feature/` to `spec/features/<feature-name>/` and fill in:
   - `README.md` — Overview, status, components affected
   - `design.md` — Technical design and API contracts
   - `user-stories.md` — User stories with acceptance criteria **and agent assignment map** (every story must map to implementing + validating HASTE agents: `backend-dev`, `gis`, `ui`, `security`, etc.)
   - `plan.md` — Phased execution plan with agent names in the Agent column (Phase 1: Core Library → Phase 2: API → Phase 3: UI → Phase 4: Integration)
3. If a spec exists, read it and validate the plan against current codebase state.
4. Explore the codebase to understand the current architecture and relevant components.
5. Break the work into concrete, actionable tasks with acceptance criteria.
6. **Map every task and story to a HASTE agent** using the assignment rules in `.github/copilot-instructions.md` (Agent ↔ Story Mapping section). Never use generic roles like "Developer" or "DevOps Engineer" — use agent names.
7. Identify dependencies between tasks and suggest a build order.
8. Flag risks, edge cases, and potential blockers.
9. Include a testing strategy referencing `test-plan.md`.
10. Estimate complexity: Small (< 1 day), Medium (1-3 days), Large (3+ days).
11. If the feature involves an architecture change, note that an ADR is needed in `spec/architecture/decisions/`.

## Output

The spec files in `spec/features/<feature-name>/` with at minimum `README.md`, `design.md`, and `plan.md` filled in. Plus a summary of the plan.
