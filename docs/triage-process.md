# Vulnerability Triage Process

How the HASTE maintainers handle security signals — Dependabot alerts, CodeQL findings, secret-scan results, and externally-reported vulnerabilities.

This document covers the **internal triage workflow**. For instructions on how to **report a vulnerability** to Microsoft, see [SECURITY.md](../SECURITY.md) and [aka.ms/SECURITY.md](https://aka.ms/SECURITY.md).

Companion document: [known-vulnerabilities.md](known-vulnerabilities.md) — the running log of dismissed/risk-accepted alerts and their rationale.

---

## Scope

In-repo security signals:

- **Dependabot** alerts (root and `ui/` package graphs).
- **CodeQL** findings (`.github/workflows/codeql.yml`, runs on every PR and weekly on `main`).
- **GitHub secret scanning** alerts (push protection + repo scan).
- **External vulnerability reports** routed via [SECURITY.md](../SECURITY.md) and MSRC.

## Ownership

- **Primary owners:** Repo maintainers listed in [`.github/CODEOWNERS`](../.github/CODEOWNERS) (`@microsoft/haste-maintainers`).
- **External report coordination:** Microsoft Security Response Center (MSRC) via [aka.ms/SECURITY.md](https://aka.ms/SECURITY.md). Maintainers cooperate; MSRC drives disclosure timing.
- **Final risk-acceptance sign-off:** Project lead. For anything labelled `Critical` or `High` the sign-off must be in writing (PR description, comment on the dismissed alert, or commit message).

## Triage cadence and SLAs

| Signal | Initial triage | Remediate or waive by |
|---|---|---|
| Dependabot — Critical | 1 business day | 7 days |
| Dependabot — High | 5 business days | 14 days |
| Dependabot — Medium | 10 business days | 30 days |
| Dependabot — Low | Best-effort during normal review | Document if deferred > 90 days |
| CodeQL — High or Critical | At PR review (blocks merge) | Before merge |
| CodeQL — Medium / Low | At PR review | Before next release |
| Secret scanning — confirmed leak | Within 24 hours | Rotate immediately; revoke first, then push fix |
| External report (MSRC) | Acknowledge within 5 business days | Per MSRC policy |

"Initial triage" = an explicit decision is recorded (fix queued / dismiss with reason / risk-accept).

A monthly sweep reviews all dismissed alerts older than 90 days to confirm waivers are still valid (e.g., upstream may have shipped a fix, threat model may have changed).

### Weekly dependency-exception review

Some dependency exceptions are higher-risk than a routine dismissal and are
reviewed **weekly** rather than on the monthly sweep — currently the deferred
**GDAL 3.9.2** CVEs (alerts #33/#34/#38), which run with compensating controls
instead of a patch (see [known-vulnerabilities.md](known-vulnerabilities.md)
Root Cause C).

- **Owner:** Project lead (or delegate) — same sign-off authority as a
  High-severity waiver.
- **Cadence:** Weekly, until the exception closes.
- **Checklist each week:**
  1. Has a trusted, prebuilt pip wheel for the patched GDAL 3.13+ line become
     available for HASTE's Linux runtime? (If yes → schedule the upgrade and
     close the exception.)
  2. Are the compensating controls still in force in code (driver allowlist,
     ingestion size/type checks, SSRF/redirect guards)? Confirm CI is green.
  3. Has the threat model or deployment model changed in a way that removes the
     pip-wheel dependency?
- **Exit criterion:** A trusted GDAL 3.13+ wheel (or a deployment-model change
  that removes the externally-hosted-wheel dependency) is adopted; the alerts
  are then remediated and this exception removed.

## Workflow per signal

### Dependabot alert

1. **Read** the alert: package, advisory ID (CVE/GHSA), severity, affected paths.
2. **Reachability check** — does any application code path actually reach the vulnerable function? For UI deps, are they used in production code or only in build/dev tooling?
3. **Decide:**
   - **Fix:** accept the Dependabot PR, or open a manual upgrade PR if the bot's PR is blocked (peer dep conflicts, breaking changes). Regenerate lockfiles.
   - **Dismiss as `tolerable_risk`:** only if (a) not reachable from app code, or (b) blocked on upstream and risk is bounded. Record the reason in [known-vulnerabilities.md](known-vulnerabilities.md) **and** in the GitHub dismissal comment.
   - **Dismiss as `not_used`:** dependency is dev-only and unreachable in production.
4. **Verify** in the next Dependabot rescan (`gh api repos/microsoft/haste/dependabot/alerts?state=open`).

### CodeQL finding

1. Findings appear as PR review comments and on the Security tab.
2. **High/Critical** findings block PR merge — fix or document a justified dismissal in the PR conversation.
3. **Medium/Low** findings — fix in the same PR if cheap; otherwise file a follow-up issue with a target release.
4. Periodic dismissals require justification recorded on the alert.

### Secret scanning alert

1. Push protection should catch most leaks before commit; if a leak is committed:
   - **Rotate first** — revoke the leaked credential immediately on the issuing system (Azure portal, key vault, etc.).
   - **Then** force-remove the secret from history if it's still in the working tree, or document its presence if the rotation makes the leak benign (well-known dev keys, expired tokens).
2. Update `.gitleaks.toml` / `detect-secrets` baseline only after rotation; never to suppress an unresolved leak.

### External report (MSRC)

1. Reports come via [aka.ms/SECURITY.md](https://aka.ms/SECURITY.md) → MSRC.
2. MSRC notifies maintainers via private channel and assigns a case number.
3. Maintainers cooperate with MSRC on reproducer, fix, and disclosure timing. Public commit / advisory waits until MSRC says go.

## Escalation

- **Critical** severity or evidence of active exploitation in the wild → notify MSRC and project lead immediately; assume incident-response cadence rather than the table above.
- Cannot remediate within the SLA window → open a tracking issue, document the blocker (upstream not patched, breaking-change cost, etc.), and obtain explicit risk-acceptance sign-off recorded on the issue.
- Disagreement on disposition → escalate to the security review team contact (the HASTE maintainers).

## Records

- **Open and historical alerts:** GitHub Security tab + `gh api repos/microsoft/haste/dependabot/alerts`.
- **Documented dismissals and waivers:** [known-vulnerabilities.md](known-vulnerabilities.md).
- **External reports:** MSRC case files (private).

## Reviewing this process

Revisit this document whenever:

- The OSS deployment / hosting model changes (e.g., HASTE adds a hosted service).
- New scanning tools are added (e.g., container image scanning, Snyk).
- The maintainer set changes materially.
- A real incident exposes a gap.
