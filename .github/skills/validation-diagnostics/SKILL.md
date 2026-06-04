---
name: validation-diagnostics
description: "Validation and diagnostic skill for HASTE. Compare planned vs implemented work, generate diagnostic reports, and feed misses back into skill refinement. Use when: 'validate implementation', 'compare to spec', 'diagnostic report', 'drift analysis', 'coverage check', 'implementation review'."
source: "HASTE validation practices"
domain: "quality"
level: "intermediate"
agents: ["backend-validation", "ui-validation", "security-validation", "orchestrator"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Validation & Diagnostics

## Overview

Structured process for comparing planned vs implemented work, generating diagnostic reports, and identifying gaps. Used by validation agents to provide concrete, evidence-based assessments.

## Key Concepts

### The Trust Problem
Agents will claim work is complete when it isn't. Validation must be:
- **Observable** — Based on test output, not agent claims
- **Deterministic** — Same input produces same verdict
- **Evidence-based** — Every finding references concrete code or test results
- **Structured** — Consistent format for easy human review

## Patterns & Techniques

### Planned vs Implemented Comparison

**Step 1: Extract planned items**
From the spec, issue, or plan, extract a checklist of:
- Acceptance criteria
- Required endpoints/functions
- Expected model fields
- Required test coverage
- UI components specified

**Step 2: Verify each item**
For each planned item, check:
- Does the code exist? (file search, grep)
- Does it match the specification? (read and compare)
- Is it tested? (find corresponding test)
- Does the test pass? (run and capture output)

**Step 3: Generate drift report**
```markdown
## Drift Analysis: [Feature]

| Planned Item | Status | Evidence |
|-------------|--------|----------|
| [spec item] | ✅ Implemented | [file:line] |
| [spec item] | ⚠️ Partial | [what's missing] |
| [spec item] | ❌ Not found | [searched in...] |
| [unplanned] | ⚡ Scope creep | [file:line] |
```

### Diagnostic Report Template

```markdown
## Diagnostic Report: [Component/Feature]

### Summary
[1-2 sentence verdict]

### Test Results
```
[Actual test output — copy/paste, not paraphrased]
```

### Code Quality
| Metric | Result |
|--------|--------|
| Type hints present | ✅ / ❌ |
| Pydantic models used | ✅ / ❌ |
| Config class used (no hardcoded secrets) | ✅ / ❌ |
| Error handling present | ✅ / ❌ |
| Logger used (not print) | ✅ / ❌ |

### Findings
| # | Severity | Finding | Location | Recommendation |
|---|----------|---------|----------|----------------|
| 1 | [High/Med/Low] | [what] | [file:line] | [fix] |

### Coverage Gaps
[Code paths without tests]

### Verdict
✅ PASS | ⚠️ CONDITIONAL PASS | ❌ FAIL
[Explanation with evidence]
```

### HASTE-Specific Validation Checks

| Component | Must Verify |
|-----------|-------------|
| New API endpoint | Auth level, Pydantic validation, error codes, CORS |
| New processor | Config injection, logger usage, error handling |
| New data model | Pydantic BaseModel, field types, validation rules |
| New data layer | Abstract interface compliance, connection handling |
| New UI component | FluentUI usage, no alt frameworks, responsive |
| Geospatial code | CRS preservation, COG compliance, GDAL/rasterio usage |

### Feedback Loop
When validation reveals a miss:
1. Document the miss in the diagnostic report
2. Identify the pattern (was it a convention violation? missing test? spec ambiguity?)
3. Propose a skill update or instruction addition to prevent recurrence
4. Flag to the Orchestrator for tracking

## Decision Framework

| Validation Result | Action |
|-------------------|--------|
| All checks pass, tests green | ✅ Approve |
| Minor issues, tests pass | ⚠️ Conditional — list issues for human review |
| Tests fail | ❌ Block — must fix before proceeding |
| Scope creep detected | ⚠️ Flag — human decides if extra work is acceptable |
| Spec ambiguity found | ⚠️ Flag — needs clarification before validation |

## Common Pitfalls

- **Accepting "tests passed" without seeing output** — Always run and capture
- **Validating only happy path** — Check error handling and edge cases
- **Skipping convention checks** — HASTE has specific patterns that must be followed
- **Not checking for scope creep** — Extra changes can introduce regressions
