# Plan: shared job progress

## Tasks

| Task | Agent | Status |
|---|---|---|
| Safe job-scoped output discovery | backend-dev | done |
| Partial/empty/non-finite TensorBoard handling | backend-dev | done |
| Shared running/terminal progress updates | backend-dev | done |
| Live subprocess streams and stage messages | backend-dev | done |
| Review: descriptor-anchored output reads, unbuffered children, terminal stage history | backend-dev | implemented; Linux descriptor/race validation passed |
| Empty-message and indeterminate UI states | ui | done |
| Merge refreshed lifecycle/main while retaining upstream active-job tests and progress tests | backend-dev; ui | done |
| Regression and integration validation | backend-validation; ui-validation | prerequisite and neutral host integration complete; earlier live evidence is retained below |

## Validation

- Unit tests for exact/nested/prefix discovery, ambiguity, missing files,
  and traversal/symlink boundaries. Exercise symlinked work roots,
  job/task ancestors, output files, and replacements between discovery,
  final open, and delayed chunk consumption on Linux. Native Windows must
  fail closed when descriptor APIs are unavailable.
- Real TensorBoard fixtures for empty and growing event files, epoch zero,
  missing/non-finite metrics, and completed versus running epoch counts.
- Processor tests for successful completion without telemetry and running
  polling before metrics are available. Cover failure/cancellation before
  the first poll, complete timestamped stage history, repeated stages, error
  detail privacy, and cleanup after telemetry collection. Direct and
  queue-owned cancellation must retain history, tolerate unavailable
  telemetry, and preserve actual provider state when cancellation is too late.
- Subprocess tests that observe ordinary, non-flushing Python stdout/stderr
  before child completion, with inherited unbuffered mode explicitly unset
  in the test parent.
- UI helper tests plus lint/build and deterministic browser checks.
- Revalidate this prerequisite after merging the updated lifecycle prerequisite,
  then verify the final backend-neutral integration separately.

## Current evidence and baseline limitations

The current-main refresh passed **495 backend cases**, with 31 platform skips
and the two API guard failures reproduced on unchanged main deselected.
The active-jobs and job-progress commands passed **13 UI cases** and the
exact-lockfile production build passed. The refreshed UI has no additional
lint findings relative to current main (169 versus 173 baseline findings);
the progress components/helpers pass targeted lint. No workload, deployment
or validation VM was used for this refresh.

Focused backend tests and the UI status helper cases pass. Browser checks
exercise queued, unknown-progress, determinate, terminal, empty-message,
legacy-record, and reduced-motion behavior. The production UI build passes
with the exact locked dependencies.

The combined local runtime was observed through the live application API:
diagnostic jobs reported `InProgress` and nonzero progress before container
exit, retained their identities across a queue-host restart, and reached
complete progress only after output persistence. Fresh imagery processing
and labeling also completed successfully.

Earlier full-library runs excluded `test_artifacts.py::test_zip`, which
called the removed `ArtifactProcessor.zip` method; current main no longer
contains that case. Full UI lint still reports the baseline findings noted
above. All changed progress UI files pass targeted lint.

The review follow-up uses the existing Python 3.11 test interpreter directly,
with explicit `PYTHONPATH` and HTTP blocked; it does not synchronize or install
dependencies. Streaming, terminal-history, native Windows fail-closed, and
selected metadata-fencing/cleanup checks report 44 passed and 30 POSIX-only
skips. Changed Python files pass Black, isort, and flake8.

The parent restored the missing `python:3.11-slim` test image and ran the
descriptor/path suites as a non-root Linux user, with networking disabled
and source mounted read-only: 27 passed, with the Windows-only contract
skipped. These exercise real job/task symlinks, discovery/open replacement
races, pinned directory inodes, and replacement after final open. This
Linux run covers the filesystem helper; the dependency-heavy LocalRunner
bridge remains covered by the separate host contract tests, not claimed
as a full Linux application run.
