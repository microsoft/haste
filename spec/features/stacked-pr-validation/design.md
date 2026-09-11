# Design: stacked pull-request validation

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
