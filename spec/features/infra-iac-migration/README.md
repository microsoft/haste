# Feature: Infrastructure as Code Migration (Bicep + azd)

**Status:** implemented
**Author:** HASTE engineering team
**Date:** 2026-06-25
**Target Release:** TBD
**Priority:** P1
**Work Item:** TBD

## Summary

Replace the bash-based HASTE infrastructure scripts (`setup/setup_infra.sh`,
`setup/deploy_apps.sh`) with declarative Bicep modules orchestrated by the
Azure Developer CLI (`azd`). The new setup is cross-platform, previewable with
`what-if`, source-controlled and reviewable, and reproduces the current
deployed state before any cleanup so it is an accurate mirror of production.

## Motivation

- **Bash-only, doesn't run on Windows.** The team works on Windows/PowerShell;
  the current scripts require bash + `jq`.
- **No preview or validation.** Imperative `az ... create` calls guarded by
  ad-hoc existence checks; no `what-if`, no type checking, best-effort
  idempotency.
- **Unmaintainable size and duplication.** ~1,670 combined lines across two
  scripts that re-declare the same config and disagree on versions
  (`v1.2.0` vs `v1.4.1`).
- **Inline ARM/Bicep as escaped strings** for APIM and the Batch pool — not
  lintable or reusable.
- **Manual `<REPLACE_ME>` placeholders** edited in place.
- **Manually-created resources** (e.g. ACS, a custom invitation role) exist
  out-of-band and are not captured in any source-controlled artifact.

If we don't fix this, every deploy stays fragile, undocumented drift accrues,
and onboarding/operating the platform stays high-risk.

## Success Criteria

- [x] `azd up` provisions and deploys a complete HASTE environment on Windows,
      macOS, and Linux with no bash dependency.
- [x] `az deployment sub what-if` (via `azd provision --preview`) runs clean
      against an existing environment, confirming the Bicep reflects current
      deployed state.
- [x] All resources from `setup_infra.sh` are represented as Bicep modules:
      identity, storage, network, monitoring, apim, functions, batch, frontend,
      and feature-flagged frontdoor.
- [x] The three Function Apps and the Static Web App deploy via `azd` services.
- [x] APIM operation import, admin-settings upload, and bootstrap user
      invitation run as PowerShell `azd` hooks.
- [x] The email backend (ACS) is provisioned in-IaC so there is no manually
      supplied secret; the sender domain is configurable (Azure-managed or custom).
- [x] `setup/setup_infra.sh` and `setup/deploy_apps.sh` are removed once parity
      is confirmed; `setup/README.md` and `docs/deployment.md` are updated.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `infra/` (new) | New Bicep module tree + parameters |
| `azure.yaml` (new) | azd service + hook definitions |
| `api/hastefuncapi/` | Deployed via azd service (no code change) |
| `api/hastefuncqueues/` | Deployed via azd service (no code change) |
| `api/titilerfuncapi/` | Deployed via azd service (no code change) |
| `ui/` | Built and deployed via azd as the SWA (no code change) |
| `setup/` | `setup_infra.sh` + `deploy_apps.sh` retired; README rewritten |
| `docs/` | `deployment.md` updated to azd workflow |

## Related Specs

| Spec | Relationship |
|---|---|
| [ADR-0003](../../architecture/decisions/0003-bicep-azd-infra-migration.md) | Records the Bicep + azd decision |
| [architecture/overview.md](../../architecture/overview.md) | Canonical system architecture this provisions |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Bicep module + azd technical design | approved |
| [user-stories.md](user-stories.md) | User stories, acceptance criteria, agent map | approved |
| [plan.md](plan.md) | Phased execution plan | approved |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-25 | Use Bicep + azd (not Terraform, not refactored bash) | Microsoft-native, reuses existing inline Bicep, one-command cross-platform provision + deploy. See ADR-0003. |
| 2026-06-25 | Reproduce current deployed state before cleanup | IaC must mirror production, validated via `what-if`. |
| 2026-06-25 | Front Door + WAF as feature-flagged module, default off | Preserves existing `EnableFrontDoor` behavior. |
| 2026-06-25 | CI cutover deferred to a follow-up (Phase 5) | Avoid migrating IaC and CI OIDC auth at once; target is `.github/workflows/deploy-apps.yml`, not `azure-pipelines.yml` (scans only). |
| 2026-06-25 | Provision ACS in-IaC; no Key Vault | Email connection string becomes a deploy-time output, so no human-supplied secrets remain; managed-identity hardening for ACS + Batch tracked as follow-up. |
| 2026-06-25 | Parameterize email sender domain (`AzureManaged` default, `Custom` opt-in) | OSS forks avoid DNS verification; an operated deployment uses a custom domain. |
| 2026-06-25 | Keep `prefix` + `randomSuffix` naming (not azd `resourceToken`) | Matches existing deployed resource names so `what-if` stays clean; avoids destroy/recreate and keeps operator-recognizable names. |
| 2026-06-25 | Account for manually-created resources up front via an as-built inventory; do not rely on `what-if` to surface them | `what-if` on an incremental sub-scope deploy only reports changes to *declared* resources — undeclared manual resources (ACS, the custom SWA invitation role) are invisible to it, so they are inventoried and modeled in Bicep (`communication.bicep`, `roles.bicep`) before parity validation. |
| 2026-06-25 | Support both create and bring-your-own Batch via `batchAccountMode` + `batchPoolMode`; allow pool creation on an existing shared account | Self-contained forks can create a Batch account + pool; an operated deployment can reuse a shared Batch account in a separate resource group and create its pool there via a cross-RG-scoped sub-module. Pool creation is additive-only; `what-if` must cover the shared resource group and the deploy identity needs pool-write on the shared account. Configuration modes are documented in the how-to/configuration guides. |
