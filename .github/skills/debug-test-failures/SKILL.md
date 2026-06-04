---
name: debug-test-failures
description: "Systematic debugging workflow for test failures. Use when tests are failing, a CI build is red, or when asked to debug test issues."
source: "Internal engineering practices"
domain: "testing"
level: "intermediate"
agents: ["backend-dev", "gis", "ui", "backend-validation"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
allowed-tools: shell
---

# Debug Test Failures

## Overview

A systematic process for diagnosing and fixing test failures. Use this skill when tests fail, CI is red, or someone reports a broken build. The key principle: **find the root cause, not just the symptom**.

## Key Concepts

### Failure Categories
- **Deterministic failure**: Same result every time. Usually a code bug or outdated test.
- **Flaky failure**: Intermittent. Usually caused by timing, ordering, shared state, or external dependencies.
- **Environment failure**: Works locally, fails in CI. Usually paths, permissions, or missing dependencies.

## Patterns & Techniques

### Systematic Debugging Process

**Step 1: Reproduce**
Run the failing test in isolation:
```bash
# Python tests
cd hastelib && hatch run test:pytest

# UI lint
cd ui && npm run lint
```
Run it 2-3 times. If intermittent, it's likely flaky.

**Step 2: Analyze**
- Read the error message and stack trace carefully
- Identify the assertion that failed: expected vs actual values
- Check if the failure is in the test or the code under test

**Step 3: Investigate**
- Read the test code to understand what it's testing
- Read the production code being tested
- Check recent changes to both
- Common root causes:
  - Changed function signatures or return types
  - Modified data structures
  - New dependencies not mocked
  - Environment differences (paths, timezones, locale)
  - Race conditions in async code

**Step 4: Fix**
- Fix the root cause, not just the symptom
- If the test is wrong (testing outdated behavior), update the test
- If the code is wrong, fix the code
- Run the full test suite: `cd hastelib && hatch run test:pytest`

**Step 5: Report**
Summarize: root cause, fix applied, verification that all tests pass.

## Decision Framework

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| Test always fails | Code bug or outdated test | Read both, fix the wrong one |
| Test passes locally, fails in CI | Environment difference | Check paths, deps, permissions |
| Test fails intermittently | Timing, shared state, or ordering | Add isolation, remove shared state |
| Many tests fail at once | Breaking change in shared code | Find the common dependency |

## Common Pitfalls

- **Fixing the test to match broken code** — Verify the code is correct before changing the test
- **Adding sleep() to fix flaky tests** — Fix the root cause (usually missing await or shared state)
- **Only running the fixed test** — Always run the full suite to check for regressions
