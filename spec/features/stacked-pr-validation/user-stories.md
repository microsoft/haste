# User story: checks follow the pull request

## US-001

As a contributor, I want a prerequisite-based pull request to receive the
same eligible checks as a pull request to main.

Acceptance: changing a PR base to another branch does not exclude its
pull-request event. Existing path filters, permissions and publication
guards continue to apply.

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
|---|---|---|
| US-001 | backend-dev | backend-validation |
| US-002 | backend-dev | backend-validation |
| US-003 | backend-dev | backend-validation |

## US-002: independent builds do not collide

Two candidate builds get distinct immutable versions. Retrying one retains
its version, and changes to release assets after the run was created do
not change its identity. An existing wheel is reused only with matching
source and checksum; mismatched or forged metadata fails closed.

## US-003: an RC deployment has a complete artifact set

The imagery base and dependency installation work with the existing builder.
Both worker images and the wheel identify the intended source. If one image
fails, the candidate is not ready; retrying can complete it without replacing
successful artifacts. A different source SHA or missing image blocks deploy.
