---
name: dependency-update
description: "Guide for safely updating project dependencies. Use when asked to update packages, upgrade dependencies, or check for outdated libraries."
source: "Internal engineering practices"
domain: "maintenance"
level: "foundational"
agents: ["backend-dev", "security", "security-validation"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
allowed-tools: shell
---

# Dependency Update

## Overview

A structured process for safely updating project dependencies. Updates are categorized by risk level and applied in controlled batches with verification at each step.

## Key Concepts

### Semantic Versioning Risk Tiers
- **Patch** (x.x.X): Bug fixes only. Safe to batch.
- **Minor** (x.X.0): New features, backward compatible. Update in small batches.
- **Major** (X.0.0): Breaking changes. Update one at a time. Read the changelog.

## Patterns & Techniques

### Safe Update Process

**Step 1: Audit**
```bash
# Python
pip list --outdated

# JavaScript
npm outdated
```

**Step 2: Categorize** — Group by risk tier (patch, minor, major).

**Step 3: Update per batch**
1. Update the dependency
2. `cd hastelib && hatch build -t wheel` — check build
3. `cd hastelib && hatch run test:pytest` — check behavior
4. `cd ui && npm run lint` — check for new warnings
5. If tests fail, investigate and fix or revert

**Step 4: Security check** — Scan for known vulnerabilities.

**Step 5: Commit** — One commit per logical group:
```
chore(deps): update [package] from vX to vY
```

## Decision Framework

| Update Type | Risk | Strategy |
|------------|------|----------|
| Patch | Low | Batch all, update together |
| Minor (well-known pkg) | Low-Med | Small batches of 3-5 |
| Minor (niche pkg) | Medium | One at a time, check changelog |
| Major | High | One at a time, read migration guide |
| Security fix | Critical | Update immediately, regardless of type |

## Common Pitfalls

- **Updating everything at once** — If tests fail, you can't tell which update caused it
- **Skipping the changelog** — Major updates often require code changes
- **Ignoring transitive dependencies** — A safe direct dep can pull in a vulnerable transitive dep
