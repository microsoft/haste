# Execution Plan: hastegeo CI build and release pipeline

## Tasks

| Phase | Task | Agent | Status |
|---|---|---|---|
| 1 | Merge main and resolve PR conflicts | `backend-dev` | resolved; merge commit pending |
| 1 | Add feature spec and acceptance criteria | `backend-dev` | complete |
| 2 | Extract pure version resolver; make Hatch build-only | `backend-dev` | complete |
| 2 | Add trusted wheel validator/publisher | `backend-dev` | complete |
| 3 | Split read-only build and trusted publish workflow jobs | `backend-dev` | complete |
| 3 | Add automatic trusted RC publication | `backend-dev` | in-progress |
| 3 | Keep protected environment gate for stable releases | `backend-dev` | blocked: repository admin required |
| 4 | Connect RC publication to coherent ACR image tags | `backend-dev` | complete |
| 4 | Harden Function wheel resolution and deployment failure handling | `backend-dev` | complete |
| 5 | Make cleanup report-only and fail-closed | `backend-dev` | complete |
| 5 | Pin action/tool versions | `backend-dev` | complete |
| 6 | Add tests and validate Docker/package/workflows | `backend-validation` | targeted tests complete; full suite blocked by pre-existing Azurite Queue auth issue |
| 6 | Update PR and run pre-landing review | `backend-validation` | pending |

## Dependencies

1. Version resolver precedes wheel validation and workflows.
2. Trusted publication precedes ACR image integration.
3. Deploy and cleanup hardening can proceed after the spec.
4. Tests must cover all scripts before publication is enabled.

## Rollout Gate

Stable publication jobs use `HASTEGEO_PUBLISH_ENABLED == 'true'` and the
protected `hastegeo-release` environment. They also require
`HASTEGEO_RELEASE_APPROVAL_CONFIGURED == 'true'`, which an administrator sets
only after required reviewers are active. Merge with publication disabled,
inspect the first build artifacts, configure required reviewers, then enable
and manually approve the first release.

Same-repository PR RCs publish automatically from trusted `workflow_run` code
and build final development ACR images once. The target environment is selected
by `HASTEGEO_RC_ENVIRONMENT`. Set
`HASTEGEO_RC_PUBLISH_ENABLED=false` only as an emergency kill switch.
