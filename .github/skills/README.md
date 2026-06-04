# HASTE Agent Skills Library

This directory contains **structured skills** — distilled, actionable knowledge that agents can use during code generation, architecture decisions, and code review.

## How Skills Work

Each skill lives in its own subdirectory as a `SKILL.md` file. The Copilot skill discovery system reads `SKILL.md` files and makes them available to agents automatically when relevant to the current task.

Skills can also include scripts, examples, and other resources alongside `SKILL.md`.

## Available Skills

### HASTE-Specific Skills

| Skill | Domain | Level | Status | Agents |
|-------|--------|-------|--------|--------|
| [`security-analysis`](./security-analysis/SKILL.md) | security | intermediate | draft | security, security-validation |
| [`imagery-provider-adaptation`](./imagery-provider-adaptation/SKILL.md) | geospatial | advanced | draft | gis, backend-dev |
| [`deterministic-scripts`](./deterministic-scripts/SKILL.md) | operations | foundational | draft | backend-dev, gis, backend-validation |
| [`validation-diagnostics`](./validation-diagnostics/SKILL.md) | quality | intermediate | draft | backend-validation, ui-validation, security-validation |

### General Skills

| Skill | Domain | Level | Status |
|-------|--------|-------|--------|
| [`api-design`](./api-design/SKILL.md) | architecture | intermediate | draft |
| [`copilot-cli-modes`](./copilot-cli-modes/SKILL.md) | workflows | foundational | draft |
| [`debug-test-failures`](./debug-test-failures/SKILL.md) | testing | intermediate | draft |
| [`dependency-update`](./dependency-update/SKILL.md) | maintenance | foundational | draft |
| [`release-notes`](./release-notes/SKILL.md) | documentation | foundational | draft |

## Skill Status Legend

| Status | Meaning |
|--------|---------|
| `draft` | Created, awaiting domain expert review |
| `review` | Under review by domain expert |
| `validated` | Reviewed and approved by domain expert |
| `stale` | Source material updated; skill needs refresh |

## Adding a New Skill

1. Create a subdirectory: `.github/skills/<skill-name>/`
2. Create `SKILL.md` inside it following the template from the agent-customization reference
3. Set `status: draft` and `created_date`
4. Update this README
5. Request review — create a `REVIEW.md` when validated
