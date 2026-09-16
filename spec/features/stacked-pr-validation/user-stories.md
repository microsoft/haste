# User story: checks follow the pull request

## Contents

- [US-001](#us-001)
- [Agent Assignment Map](#agent-assignment-map)
- [US-002: independent builds do not collide](#us-002-independent-builds-do-not-collide)
- [US-003: an RC deployment has a complete artifact set](#us-003-an-rc-deployment-has-a-complete-artifact-set)
- [US-004: producer updates do not break the running publisher](#us-004-producer-updates-do-not-break-the-running-publisher)

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
| US-004 | backend-dev | backend-validation |

## US-002: independent builds do not collide

Once the running publisher supports the run-bound protocol, two candidate
builds get distinct immutable versions. Retrying one retains
its version, and changes to release assets after the run was created do
not change its identity. An existing wheel is reused only with matching
source and checksum; mismatched or forged metadata fails closed.

## US-003: an RC deployment has a complete artifact set

The imagery base and dependency installation work with the existing builder.
Both worker images and the wheel identify the intended source. If one image
fails, the candidate is not ready; retrying can complete it without replacing
successful artifacts. A different source SHA or missing image blocks deploy.

## US-004: producer updates do not break the running publisher

A branch with the updated producer still publishes through an older
default-branch publisher using the legacy name and version rules. Once the
updated publisher is active, it continues to accept older PR producers
while updated producers select the new protocol. A protocol change must
not silently renumber an existing run or downgrade its provenance.

Acceptance: cover old producer/new publisher, new producer/old publisher,
and new producer/new publisher; validate artifact names and versions together.
Unknown capabilities, lookup failures, ambiguous artifacts, and wrong run
attempts fail explicitly. Legacy artifacts never claim verified-set metadata.
