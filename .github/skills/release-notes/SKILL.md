---
name: release-notes
description: "Generate release notes from commit history. Use when asked to draft release notes, create a changelog, or summarize changes for a release."
source: "Internal engineering practices"
domain: "documentation"
level: "foundational"
agents: ["orchestrator", "backend-dev"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Release Notes

## Overview

A structured process for generating release notes from commit history. Groups changes by type, highlights breaking changes, and produces user-friendly summaries.

## Patterns & Techniques

### Generation Process

**Step 1: Gather changes**
```bash
git log --oneline $(git describe --tags --abbrev=0)..HEAD
```

**Step 2: Categorize** using conventional commit prefixes:
- **🚀 Features** (`feat:`)
- **🐛 Bug Fixes** (`fix:`)
- **📚 Documentation** (`docs:`)
- **🔧 Maintenance** (`chore:`, `refactor:`)
- **⚠️ Breaking Changes** (`BREAKING CHANGE` or `!`)

**Step 3: Write** using the template:

```markdown
# Release vX.Y.Z

## Highlights
Brief summary of the most important changes (2-3 sentences).

## 🚀 Features
- Description of feature (#PR)

## 🐛 Bug Fixes
- Description of fix (#PR)

## ⚠️ Breaking Changes
- What changed and migration steps

## 📚 Documentation
- What was updated

## 🔧 Maintenance
- Internal changes
```

**Step 4: Review**
- All significant changes included
- PR/issue references correct
- Breaking changes include migration instructions

## Common Pitfalls

- **Listing commit messages verbatim** — Rewrite for the reader, not the committer
- **Missing breaking changes** — Always call these out prominently with migration steps
- **No highlights section** — Users want a 2-sentence summary, not a raw list
