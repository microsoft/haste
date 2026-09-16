# Design: stacked pull-request validation

## Contents

- [Scope](#scope)
- [Trust boundary](#trust-boundary)
- [Validation](#validation)
- [RC identity and publication](#rc-identity-and-publication)
- [Compatible protocol rollout](#compatible-protocol-rollout)

## Scope

Remove only the default-branch filter on existing `pull_request` triggers.
Keep path filters, push/schedule behavior, permissions, action pins, and
build/publish conditions unchanged.

Secret-scan failures must include actionable file/line diagnostics while
fully redacting matched values. Verbose output stays paired with
`--redact=100` and a nonzero findings exit code in every scan mode. Historical
false positives are handled by exact fingerprints, never by excluding
whole test directories or weakening detection rules.

## Trust boundary

The wheel build remains credential-free. The trusted publisher continues
to run from the default branch and verifies the source repository, open
pull request, exact head commit, and artifact contents. This change does
not grant source builds publishing permissions or add a new Azure workflow.

## Validation

A release-policy regression checks that all six validation workflows
accept pull requests against stack branches. Existing policy tests keep
credential separation and artifact-publication guards intact.

## RC identity and publication

CI candidates use `X.Y.Zrc<build-run-id>`. Their release baseline is the
latest stable asset created strictly before that GitHub build run.
Equal timestamps are excluded because GitHub timestamps can have
second-level precision and cannot establish ordering within that second.
The source SHA, creation cutoff, run ID, release baseline, version and
source timestamp form a frozen build identity. The trusted publisher
derives the same identity independently instead of allocating another
version from current release state.

The wheel build emits a checksum-bearing manifest without write credentials.
The publisher verifies it against trusted run metadata, validates the wheel,
and permits an existing RC only when its bytes and provenance agree.
Conflicting assets are never overwritten. Publication is grouped by
immutable version, not one shared pending slot across unrelated PRs.

Each successful image build records its source, version, registry reference
and digest. Only a complete matching pair can produce the deployment-set
manifest; an RC deployment verifies that manifest against its app source.
Rerunning a build keeps its identity and resumes missing images.

An image is locked only when both `writeEnabled` and `deleteEnabled` are
explicitly false. Missing or non-boolean lock attributes are rejected when
recording provenance, reusing a legacy image, and checking a deployment.

Wheel upload/download artifacts are scoped to the upstream run attempt.
Image builds for the same family/version serialize; already-uploaded image
evidence must compare identically before reuse. Publishing manifests stores
only registry-independent image references and a registry fingerprint, never
actual internal registry names or credentials. Deployment verifies that
fingerprint and the locked image digests before changing app settings.

Stable release rules, protected default-branch publication, exact-head/fork
guards and explicit deployment approval remain unchanged. Legacy candidates
without provenance cannot be treated as new verified deployment sets.

## Compatible protocol rollout

Producers negotiate against `.github/hastegeo-artifacts.json` on the
repository's actual default branch, never their PR checkout. Until the
running publisher advertises the new protocol, preserve both its legacy
artifact name and its legacy RC version rules. A missing capability file
selects this explicit compatibility mode; authentication, network, malformed
metadata, and unknown protocol errors fail instead of silently downgrading.

The updated trusted publisher accepts both legacy artifacts and the new
run-attempt artifacts, selecting the contract from the triggering run's
actual artifacts. Older PR branches therefore keep working after a publisher
upgrade. A rerun with existing artifacts retains its original protocol.
Ambiguous, expired, or wrong-attempt inputs fail closed.

Legacy publication retains the existing no-overwrite policy and image
locking, but must not claim new verified-set provenance. Only run-bound
builds can publish complete source/checksum/digest manifests. This migration
restores existing publishing without deploying apps, changing Azure
configuration, or requiring a repository-variable toggle.
