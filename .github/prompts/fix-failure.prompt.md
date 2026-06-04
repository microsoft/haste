---
description: "Fix a failing test or build"
agent: backend-dev
tools: ["read", "edit", "search", "execute"]
argument-hint: "Paste the error message or describe the failure"
---

Diagnose and fix the described test or build failure.

## Instructions

1. Run the failing command to reproduce the error.
2. Read the error message and stack trace carefully.
3. Search the codebase for the relevant source code.
4. Identify the root cause — not just the symptom.
5. Implement the minimal fix.
6. For Python: run `cd hastelib && hatch run test:pytest` to confirm the fix.
7. For UI: run `cd ui && npm run lint` to ensure no lint regressions.
8. Summarize what was wrong and what you changed.
