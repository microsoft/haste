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
| 3 | Publish stable automatically on merge to `main` | `backend-dev` | complete |
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

Stable publication is gated solely by `HASTEGEO_PUBLISH_ENABLED == 'true'`.
Merging a PR into `main` is the release approval: the branch ruleset is active
with no bypass actors and requires an approving review plus passing status
checks, so no commit reaches `main` unreviewed.

Superseded: stable publication originally also required
`HASTEGEO_RELEASE_APPROVAL_CONFIGURED == 'true'` and the protected
`hastegeo-release` environment. That was a bring-up gate — merge with
publication disabled, inspect artifacts, then enable — and it was never turned
on, so no stable wheel published for the pipeline's whole life. Both controls
remain in force for the destructive RC deletion job in `rc-cleanup.yml`.

Same-repository PR RCs publish automatically from trusted `workflow_run` code
and build final development ACR images once. The target environment is selected
by `HASTEGEO_RC_ENVIRONMENT`. Set
`HASTEGEO_RC_PUBLISH_ENABLED=false` only as an emergency kill switch.

Known gap: minor and major stable releases have no automated path. The publisher
accepts only `push` and same-repository `pull_request` upstream events, so a
`workflow_dispatch` build carrying `bump` or `set_version` is never published.
