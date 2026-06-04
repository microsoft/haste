---
description: "Prepare a pull request with title, description, and checklist"
tools: ["read", "search"]
---

Prepare a pull request description for the current changes.

## Instructions

1. Identify what files have changed (staged + unstaged).
2. Summarize the changes into a clear PR description.

## Output Format

```markdown
## PR Title
<conventional commit style title>

## Description
<2-3 sentence summary of what changed and why>

## Changes
- <bullet list of key changes>

## Testing
- [ ] All existing tests pass
- [ ] New tests added for new behavior
- [ ] Manual testing performed (describe if applicable)

## Checklist
- [ ] Code follows project conventions
- [ ] No secrets or credentials committed
- [ ] Documentation updated (if applicable)
- [ ] No breaking changes (or documented in description)
```
