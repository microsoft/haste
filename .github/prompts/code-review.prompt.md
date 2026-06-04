---
description: "Review staged or recent changes for bugs and security issues"
tools: ["read", "search"]
---

Review the current changes (staged, unstaged, or recent commits) for quality and security issues.

## Instructions

1. Identify what files have changed and what the changes do.
2. Check for:
   - Bugs and logic errors
   - Security vulnerabilities (OWASP Top 10)
   - Missing error handling
   - Breaking changes to public APIs
   - Missing or inadequate tests
3. Provide findings sorted by severity (Critical → Low).
4. If no issues are found, respond with "✅ LGTM — No issues found."
5. End with a summary: total issues by severity.
