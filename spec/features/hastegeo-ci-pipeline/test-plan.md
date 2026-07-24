# Test Plan: hastegeo CI build and release pipeline

## Test Strategy

| Level | Scope | Tool | Goal |
|---|---|---|---|
| Unit | Version, wheel policy, toggles, cleanup | `unittest` / pytest runner | Deterministic positive and negative behavior |
| Package | Wheel filename and METADATA | Hatch + `zipfile` | Exact PEP 440 artifact |
| Docker | Editable Function install | Docker | Local source path works |
| Workflow | YAML, permissions, pins, outputs | Static tests | Least privilege and valid wiring |
| Integration | Automatic trusted RC publication and ACR build | GitHub Actions | Exact matching deployable artifact refs |

## Unit Scenarios

| ID | Scenario | Expected |
|---|---|---|
| UT-001 | Stable assets include RCs | Latest stable ignores RCs |
| UT-002 | RC1 and RC2 exist | Next RC is RC3 |
| UT-003 | Release query fails | Resolver raises; no fallback |
| UT-004 | Same SHA has stable tag and asset | No-op |
| UT-005 | Same SHA has tag but missing asset | Rebuild same version |
| UT-006 | Tag points to another SHA | Hard failure |
| UT-007 | RC artifact claims stable filename | Publisher rejects |
| UT-008 | Filename and METADATA differ | Publisher rejects |
| UT-009 | Existing asset name | Publisher rejects; no clobber |
| UT-009a | Stable target exists before RC publish | Publisher rejects the RC |
| UT-010 | Requirements toggle repeated | One active source line |
| UT-011 | Cleanup retain file missing | Hard failure |
| UT-012 | Cleanup keep is negative | Validation failure |
| UT-013 | Weekly cleanup | Report only, no delete calls |
| UT-014 | `rc01` deploy input | Canonicalizes to `rc1` |

## Integration Scenarios

| ID | Scenario | Expected |
|---|---|---|
| IT-001 | Build `1.0.26rc1` wheel | Filename and METADATA match |
| IT-002 | Function API Docker build | `hastegeo` loads from `/home/hastelib/src` |
| IT-003 | Invalid wheel version deploy | Failure before Azure login/mutation |
| IT-004 | `func publish` exits non-zero | Deployment workflow fails |
| IT-005 | Same-repo RC run | Wheel and both exact-version ACR tags appear in summary |
| IT-006 | Main run repeated at same SHA | No second stable version |
| IT-007 | Single ACR image build | Each Dockerfile builds once after RC publication |

## Workflow Security Assertions

- Build job permissions are `contents: read`.
- Build checkout sets `persist-credentials: false`.
- Build job receives no `GH_TOKEN`, Azure secrets, or OIDC permission.
- Publish job uses `contents: write`, protected environment, and no PR checkout.
- Image job executes trusted inline Azure commands rather than PR shell scripts.
- Fork PR condition skips publish and image jobs.
- Every external action is pinned to a full SHA.

## Sign-off Criteria

- [ ] All unit and package tests pass.
- [ ] Targeted Function Docker build passes.
- [ ] Full hastelib regression suite passes.
- [ ] No release asset was overwritten during testing.
- [ ] PR is mergeable and required checks are visible.
- [ ] Pre-landing review reports zero Critical/High findings.
