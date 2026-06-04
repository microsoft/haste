---
name: security-analysis
description: "Dependabot and security analysis skill for HASTE. Parse alerts, group related vulnerabilities, apply severity rules, and produce structured reports. Use when: 'Dependabot alert', 'security scan', 'vulnerability triage', 'dependency audit', 'npm audit', 'pip audit', 'CVE analysis'."
source: "HASTE security practices, OWASP, NVD"
domain: "security"
level: "intermediate"
agents: ["security", "security-validation"]
created_date: "2026-04-27"
last_validated: ""
validated_by: ""
status: "draft"
---

# Security Analysis

## Overview

Structured process for triaging Dependabot alerts, grouping related vulnerabilities, applying severity rules, and producing actionable reports for HASTE's Python and JavaScript dependency stacks.

## Key Concepts

### HASTE Dependency Landscape

| Stack | Location | Tool | Key Risks |
|-------|----------|------|-----------|
| Python (API) | `api/hastefuncapi/requirements.txt` | `pip audit` | GDAL parsing, Azure SDK, rasterio |
| Python (Queues) | `api/hastefuncqueues/requirements.txt` | `pip audit` | Same as API |
| Python (Core) | `hastelib/pyproject.toml` | `pip audit` | Geospatial libs, ML deps |
| JavaScript (UI) | `ui/package.json` | `npm audit` | FluentUI, MSAL, build tools |
| JavaScript (Root) | `package.json` | `npm audit` | Azurite (dev only) |

### Severity Rules

| Severity | Action | SLA |
|----------|--------|-----|
| Critical | Investigate immediately, create issue | Same day |
| High | Investigate promptly, create issue | 3 business days |
| Medium | Queue for next sprint | Next sprint |
| Low | Document and track | Backlog |

## Patterns & Techniques

### Alert Triage Process

**Step 1: Gather alerts**
```bash
# Python
pip audit --format json

# JavaScript
npm audit --json
```

**Step 2: Group related vulnerabilities**
- Same package, different CVEs → group together
- Same dependency chain → note the root cause package
- Transitive vs direct dependency → prioritize direct

**Step 3: Assess HASTE impact**
For each vulnerability, determine:
- Is the vulnerable code path reachable in HASTE?
- What data is at risk? (imagery, project metadata, user data)
- Is this in a production path or dev-only dependency?
- Can the vulnerability be exploited through HASTE's public interfaces?

**Step 4: Produce report**
```markdown
## Security Triage Report — [Date]

### Critical/High Findings
| Package | CVE | Severity | Component | Reachable? | Action |
|---------|-----|----------|-----------|------------|--------|

### Medium/Low Findings
| Package | CVE | Severity | Component | Action |
|---------|-----|----------|-----------|--------|

### Dependencies to Watch
[Packages with recent churn, new maintainers, or declining activity]
```

### HASTE-Specific Risk Areas

| Area | Why It Matters |
|------|---------------|
| GDAL/rasterio | File parsing vulnerabilities — common attack vector for malicious GeoTIFFs |
| Azure SDKs | Auth and credential handling — high-value targets |
| MSAL | Token handling and auth bypass — directly affects user security |
| boto3 | AWS S3 access for imagery sources — credential exposure risk |
| opencv-python | Image processing vulnerabilities — similar to GDAL risks |

## Decision Framework

| Scenario | Action |
|----------|--------|
| Critical CVE in production dependency | Immediate triage, create issue, recommend upgrade |
| High CVE in production dependency | Investigate within 3 days, create issue |
| Any CVE in dev-only dependency (azurite, vite, eslint) | Document, lower priority |
| Upgrade introduces breaking changes | Document migration steps, flag for planning |
| No fix available | Document workaround or risk acceptance rationale |

## Common Pitfalls

- **Treating all alerts equally** — Production critical > production high > dev-only
- **Ignoring transitive dependencies** — A safe direct dep can pull in vulnerable packages
- **Auto-upgrading without testing** — Always run `hatch run test:pytest` after upgrades
- **Assuming dev-only deps are safe** — Supply chain attacks can target build tools
