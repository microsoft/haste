# Feature: hastegeo CI build and release pipeline

**Status:** in-progress
**Author:** HASTE Maintainers
**Priority:** P1

## Summary

Automate release-candidate and stable `hastegeo` wheel builds while keeping
untrusted pull-request code separated from GitHub and Azure write credentials.
The same pipeline publishes coherent Azure Container Registry image tags and
gives the deployment workflow an exact wheel version to install.

## Motivation

The current manual Hatch hook mixes version resolution, wheel construction,
and GitHub release mutation. Running that hook from a pull request with a
write-scoped token creates a supply-chain risk, and remote failures can be
silently treated as successful builds. The pipeline also needs deterministic
stable releases, explicit deployable image tags, and a safe RC cleanup path.

If this feature is not completed, PR code can run with repository write
credentials, stable release reruns can publish additional versions, and failed
Function deployments can be reported as successful.

## Success Criteria

- [ ] Pull-request source builds run without repository or Azure write
      credentials.
- [ ] A trusted default-branch job automatically publishes validated same-repo
      PR RC wheels without overwriting an existing asset.
- [ ] Stable releases are idempotent for a source commit through
      `hastegeo-vX.Y.Z` tags.
- [ ] RC publication produces coherent, documented ACR image tags.
- [ ] Function deployment fails on invalid wheels or `func publish` failures.
- [ ] Scheduled cleanup reports candidates but never deletes automatically.
- [ ] Unit, packaging, Docker, and workflow tests cover positive and negative
      behavior.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/` | Build-only hook, version stamping, packaging tests |
| `api/hastefuncapi/` | Editable local install; wheel install during deploy |
| `api/hastefuncqueues/` | Editable local install; wheel install during deploy |
| `docker/` | Version-coherent RC image tags |
| `.github/workflows/` | Read-only build, trusted publish, deploy, cleanup |
| `.github/scripts/` | Version resolver, wheel publisher, cleanup validation |

## Related Specs

| Spec | Relationship |
|---|---|
| [Infra IaC migration](../infra-iac-migration/) | Existing GitHub/Azure deployment conventions |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Security boundary and release contracts | in-progress |
| [user-stories.md](user-stories.md) | Acceptance criteria and agent map | in-progress |
| [plan.md](plan.md) | Ordered implementation tasks | in-progress |
| [test-plan.md](test-plan.md) | Coverage and landing gates | in-progress |

## Decision Log

| Decision | Rationale |
|---|---|
| Hatch is build-only | PR-controlled Python never receives a write token |
| Artifact handoff to trusted publisher | Small least-privilege mutation surface |
| No `--clobber` | Published wheel URLs are immutable |
| Stable source tags | Main workflow reruns are idempotent |
| PEP 440 `rcN` | `rc01` is normalized to `rc1` by Python packaging |
| Automatic trusted RC publication | Fast dev/test handoff without exposing PR jobs to credentials |
| Protected stable environment | Human approval limits stable-release blast radius |
| Scheduled cleanup is report-only | Destructive automation is deferred until observed safely |
