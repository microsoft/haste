---
name: copilot-cli-modes
description: "Comprehensive guide to all Copilot CLI running modes: Interactive, Plan, Autopilot, Fleet, Research, Chronicle, and Delegate. Use when asked about CLI modes, workflows, or how to use Copilot CLI effectively."
source: "GitHub Docs — Copilot CLI concepts and best practices"
domain: "workflows"
level: "foundational"
agents: ["backend-dev", "gis", "ui", "orchestrator"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Copilot CLI Running Modes

## Overview

Copilot CLI provides 7 distinct running modes, each optimized for different tasks. Understanding when to use each mode is the key to effective AI-assisted development. Modes can be combined — for example, Plan → Autopilot + Fleet is a common power workflow.

---

## Mode Quick Reference

| Mode | Trigger | Autonomy | Modifies Code? | Best For |
|------|---------|----------|----------------|----------|
| **Interactive** | Default | Low — asks at every step | Yes (with permission) | Day-to-day coding, Q&A, small changes |
| **Plan** | `Shift+Tab` or `/plan` | Low — creates plan, waits for approval | No (planning only) | Complex features, multi-file refactors |
| **Autopilot** | `Shift+Tab` (cycle) or `--autopilot` | High — works until done | Yes (needs `--allow-all`) | Well-defined tasks, CI, batch ops |
| **Fleet** | `/fleet` prefix | High — parallel subagents | Yes | Large parallelizable tasks |
| **Research** | `/research` | High — autonomous research | No (report only) | Deep technical investigation |
| **Chronicle** | `/chronicle` | N/A — reads history | No | Standups, tips, self-improvement |
| **Delegate** | `/delegate` | Full — runs in cloud | Yes (creates PR) | Async work, other repos |

---

## 1. Interactive Mode (Default)

### What It Is
The standard back-and-forth mode. You prompt, Copilot responds, you guide the next step. Copilot asks for permission before making changes and checks in with you at decision points.

### When To Use
- Day-to-day coding tasks
- Quick bug fixes
- Single-file changes
- Exploratory questions about the codebase
- Tasks where you want control at every step

### Usage Scenarios

**Codebase onboarding:**
```
How is logging configured in this project?
What's the pattern for adding a new API endpoint?
Explain the authentication flow
```

**Quick fix:**
```
The login form doesn't validate email format. Fix the validation in src/components/LoginForm.tsx
```

**Git operations:**
```
Create a PR for this branch with a detailed description
Rebase this branch against main
```

### Key Commands
- Type your prompt and press Enter
- `Shift+Tab` to cycle to other modes
- `/model` to switch AI models mid-session
- `/clear` or `/new` to start fresh between unrelated tasks

### Tips
- Keep sessions focused — use `/clear` between unrelated tasks
- Use `/context` to see how much context window you've used
- Copilot reads `copilot-instructions.md` automatically

---

## 2. Plan Mode

### What It Is
A structured planning mode where Copilot analyzes your request, asks clarifying questions, and produces a detailed implementation plan with tasks and checkboxes — **before writing any code**. Plans are saved to `plan.md` in your session folder.

### When To Use
- Complex multi-file features
- Refactoring with many touch points
- New feature implementation
- Any task where you want to review the approach before execution

### When NOT To Use
- Quick bug fixes
- Single-file changes
- Simple questions

### How To Activate
- Press `Shift+Tab` to toggle into plan mode (prompts show "plan" indicator)
- Or use `/plan` command from normal mode

### Usage Scenarios

**Feature planning:**
```
/plan Add OAuth2 authentication with Google and GitHub providers
```

**Refactoring:**
```
/plan Migrate all class components to functional components with hooks
```

**Architecture change:**
```
/plan Extract the payment processing logic into a separate microservice
```

### What Happens
1. Copilot analyzes your request and codebase
2. Asks clarifying questions to align on requirements
3. Creates a structured plan with checkboxes
4. Saves plan to `plan.md`
5. Waits for your approval before implementing
6. After approval, you can:
   - **Implement manually** — `Proceed with the plan`
   - **Implement on autopilot** — "Accept plan and build on autopilot"
   - **Implement on autopilot + fleet** — "Accept plan and build on autopilot + /fleet"

### Viewing & Editing Plans
- `Ctrl+Y` — open plan in your default Markdown editor
- `/session plan` — view current plan in CLI

### The Power Workflow: Explore → Plan → Code → Commit
```
1. Explore:  "Read the authentication files but don't write code yet"
2. Plan:    /plan Implement password reset flow
3. Review:  Check the plan, suggest modifications
4. Build:   "Proceed with the plan"  (or autopilot)
5. Verify:  "Run the tests and fix any failures"
6. Commit:  "Commit these changes with a descriptive message"
```

---

## 3. Autopilot Mode

### What It Is
Hands-off autonomous mode. Copilot works through a task without waiting for your input after each step, continuing until the task is complete, a problem occurs, or you press `Ctrl+C`.

### When To Use
- Well-defined tasks with clear goals
- Implementing a plan you've already reviewed
- Batch operations (writing tests, fixing lints)
- CI/CD workflows and scripting
- Large tasks that require many steps

### When NOT To Use
- Open-ended exploration
- Tasks requiring nuanced judgment calls
- Vague or ambiguous instructions
- Tasks where you want to guide each step

### How To Activate
- Press `Shift+Tab` to cycle to autopilot mode
- Or use `--autopilot` flag from command line
- Or accept a plan with "Accept plan and build on autopilot"

### Usage Scenarios

**Implement a reviewed plan:**
```
# After creating a plan in plan mode:
"Accept plan and build on autopilot"
```

**Programmatic usage (CI/scripts):**
```bash
copilot --autopilot --yolo --max-autopilot-continues 10 -p "Write unit tests for all functions in src/utils/"
```

**Batch linting:**
```bash
copilot --autopilot --allow-all -p "Run the linter, fix all errors, and commit the changes"
```

### Permissions
When entering autopilot, you're prompted:
1. **Enable all permissions** (recommended) — equivalent to `--allow-all` / `--yolo`
2. **Continue with limited permissions** — auto-denies tool requests needing approval
3. **Cancel**

Use `/allow-all` or `/yolo` mid-session to grant full permissions later.

### Safety Controls
- `--max-autopilot-continues N` — cap the number of autonomous steps (prevents runaway loops)
- `Ctrl+C` — stop the agent at any time
- Each continuation shows premium request usage: `Continuing autonomously (3 premium requests)`

### Comparison Table
| Flag | What It Does | Autonomy Level |
|------|-------------|----------------|
| `--allow-all` / `--yolo` | Auto-approves all tool permissions | Still interactive (asks at decision points) |
| `--no-ask-user` | Suppresses clarifying questions | Semi-autonomous (no extra premium requests) |
| `--autopilot` | Full autonomous execution | Fully autonomous (continues until done) |

---

## 4. Fleet Mode (`/fleet`)

### What It Is
Parallel task execution. The main agent acts as orchestrator, breaking a large task into independent subtasks and assigning them to subagents that run simultaneously. Each subagent has its own context window.

### When To Use
- Large tasks with multiple independent steps
- Writing tests for many modules at once
- Refactoring several unrelated files
- Updating dependencies across packages
- Any parallelizable work where speed matters

### When NOT To Use
- Sequential tasks where each step depends on the previous one
- Small, focused single-step tasks
- Tasks where you need fine-grained control over order

### How To Activate
Prefix your prompt with `/fleet`:
```
/fleet Write comprehensive unit tests for all controllers in src/controllers/
```

### Usage Scenarios

**Parallel test writing:**
```
/fleet Write unit tests for UserService, OrderService, and PaymentService. Each test file should cover happy paths, error cases, and edge cases.
```

**Multi-file refactoring:**
```
/fleet Rename all instances of "userId" to "accountId" across the following directories: src/models/, src/services/, src/controllers/
```

**Documentation generation:**
```
/fleet Generate JSDoc comments for all exported functions in src/utils/, src/helpers/, and src/lib/
```

**Using specific agents per subtask:**
```
/fleet Use @tester to create tests for src/auth/. Use @technical-writer to update the API docs in docs/. Use @security-auditor to review src/payments/.
```

**Using specific models per subtask:**
```
/fleet Use Claude Opus 4.5 to refactor the database layer. Use GPT-5.3-Codex to generate the migration scripts.
```

### Combining with Autopilot
The most powerful workflow: Plan → Autopilot + Fleet
1. `Shift+Tab` into plan mode
2. Create a detailed implementation plan
3. Select "Accept plan and build on autopilot + /fleet"
4. Copilot decomposes the plan, runs subtasks in parallel, and works to completion

### Cost Consideration
Fleet spawns multiple subagents, each consuming premium requests independently. A `/fleet` task may use more total premium requests than the same task done sequentially. Use `/model` to check your current model's multiplier.

---

## 5. Research Mode (`/research`)

### What It Is
A specialized deep-research agent that produces comprehensive Markdown reports with citations. Unlike normal chat (optimized for quick answers), `/research` is optimized for thoroughness — reports can be hundreds of lines with architecture diagrams, code snippets, and citations.

### When To Use
- Deep technical investigation
- Understanding codebase architecture
- Comparing technologies or approaches
- Understanding how a library/framework works internally
- Cross-repository research

### When NOT To Use
- Quick questions ("what does this function do?")
- When you need code changes (research produces reports, not edits)
- Time-sensitive interactions (research takes longer)

### How To Activate
```
/research TOPIC
```

### Usage Scenarios

**Codebase architecture:**
```
/research What is the architecture of this codebase?
```
→ Produces architecture diagrams, component breakdowns, data flow descriptions

**Technology comparison:**
```
/research What's the difference between JWT and session-based authentication? Include pros, cons, and when to use each.
```
→ Narrative explanation with trade-off tables

**Internal patterns:**
```
/research How are feature flags implemented at our organization?
```
→ Searches org repos first, maps internal patterns

**Deep-dive into a component:**
```
/research How is the session management system implemented in this repo? Trace the full flow from login to token refresh.
```
→ Walks through actual code, follows imports, traces call chains

**How a technology works:**
```
/research How does React implement concurrent rendering? Show the actual source code and internal architecture.
```
→ Fetches real source from GitHub, prioritizes code over docs

### Viewing & Sharing Reports
- `Ctrl+Y` — open the latest report in your editor
- `/share gist research` — save as a GitHub gist
- `/share file research [PATH]` — save to a local file
- Reports stored at: `~/.copilot/session-state/SESSION-ID/research/`

### Report Types
The agent adapts its output format based on query type:
| Query Type | Format | Example |
|-----------|--------|---------|
| Process/how-to | Step-by-step guide | "How do I add an endpoint?" |
| Conceptual | Narrative + trade-offs | "What's the difference between X and Y?" |
| Technical deep-dive | Architecture diagrams + code | "How is X implemented?" |

**Tip**: Be explicit about the report type you want. "Give me a technical deep-dive into X with architecture diagrams" produces better results than "What is X?"

---

## 6. Chronicle Mode (`/chronicle`)

### What It Is
A session history analysis tool. Copilot records every session locally (prompts, responses, tools used, files modified) in a SQLite database. Chronicle reads this history to generate standups, tips, and self-improving custom instructions.

### When To Use
- Start of day: generate standup report
- Periodically: discover productivity tips
- When Copilot keeps making the same mistake: generate corrective instructions
- To recall past work: search your coding history

### How To Activate
> **Note**: Chronicle is experimental. Enable with `/experimental on` or `--experimental`.

### Subcommands

**Standup report:**
```
/chronicle standup
/chronicle standup last 3 days
```
→ Summarizes recent work: branch names, PR links, status checks

**Personalized tips:**
```
/chronicle tips
```
→ Analyzes your usage patterns and suggests features/workflows you're underusing

**Self-improving instructions:**
```
/chronicle improve
```
→ Analyzes sessions where Copilot misunderstood you or there was lots of back-and-forth, then generates custom instructions to fix the patterns

**Rebuild session index:**
```
/chronicle reindex
```
→ Rebuilds the session store from disk (after deletion, migration, or corruption)

### Usage Scenarios

**Monday morning standup:**
```
/chronicle standup last 3 days
```
→ "Last Friday you worked on the auth refactor (branch: feat/oauth2), created PR #42, and fixed 3 test failures. Thursday you debugged the payment timeout issue..."

**Discovering unused features:**
```
/chronicle tips
```
→ "You rarely use plan mode before complex tasks. Try /plan for multi-file changes — models achieve higher success rates with a concrete plan."

**Fixing recurring miscommunication:**
```
/chronicle improve
```
→ Generates a custom instruction like: "When I say 'fix the tests', I mean fix failing tests only — do not refactor passing tests or add new ones."

### Data Location
```
~/.copilot/session-state/{session-id}/
├── events.jsonl          # Full session history
├── workspace.yaml        # Metadata
├── plan.md               # Plans (if created)
└── research/             # Research reports

~/.copilot/session-store.db  # SQLite index for chronicle
```

### Session Management
- `/session` — view current session info
- `/session checkpoints` — view compaction checkpoints
- `/session plan` — view current plan
- `copilot --continue` — resume last session
- `copilot --resume` — pick a session to resume

---

## 7. Delegate Mode (`/delegate`)

### What It Is
Offloads a task to Copilot cloud agent, which runs asynchronously and creates a pull request with the results. You can continue working locally while the cloud agent works in the background.

### When To Use
- Tangential tasks you don't want to block on
- Documentation updates
- Refactoring separate modules
- Changes to other repositories
- Long-running tasks you can review later

### When NOT To Use
- Core feature work requiring tight control
- Active debugging
- Interactive exploration

### How To Activate
```
/delegate PROMPT
```

### Usage Scenarios

**Tangential task:**
```
/delegate Add dark mode support to the settings page
```
→ Cloud agent creates a PR while you keep coding locally

**Documentation:**
```
/delegate Update the API documentation to reflect the new authentication endpoints
```

**Cross-repo work:**
```
/delegate In the frontend repo, update the API client to use the new /v2/users endpoint
```

---

## Mode Composition Cheat Sheet

| Scenario | Mode Combination | Command |
|----------|-----------------|---------|
| Quick fix | Interactive | Just type the prompt |
| Complex feature | Plan → Autopilot | `Shift+Tab` to plan, then "Accept plan and build on autopilot" |
| Large parallelizable task | Plan → Autopilot + Fleet | Plan, then "Accept plan and build on autopilot + /fleet" |
| Deep investigation | Research | `/research How does X work?` |
| CI automation | Autopilot (programmatic) | `copilot --autopilot --yolo --max-autopilot-continues 10 -p "..."` |
| Background work | Delegate | `/delegate Update the docs` |
| Morning ritual | Chronicle | `/chronicle standup last 3 days` |
| Productivity review | Chronicle | `/chronicle tips` then `/chronicle improve` |

## Decision Tree

```
Is the task well-defined?
├── No  → Is it a question?
│        ├── Quick question → Interactive mode
│        └── Deep investigation → /research
└── Yes → Is it complex (multi-file)?
          ├── No  → Interactive mode
          └── Yes → Plan mode first
                    └── Plan approved?
                        ├── Parallelizable? → Autopilot + /fleet
                        ├── Sequential?     → Autopilot
                        └── Tangential?     → /delegate
```
