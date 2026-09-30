# Plan: shared job progress

## Tasks

| Task | Agent | Status |
|---|---|---|
| Safe job-scoped output discovery | backend-dev | done |
| Partial/empty/non-finite TensorBoard handling | backend-dev | done |
| Shared running/terminal progress updates | backend-dev | done |
| Live subprocess streams and stage messages | backend-dev | done |
| Review: descriptor-anchored output reads, unbuffered children, terminal stage history | backend-dev | implemented; Linux descriptor/race validation passed |
| Keep workflow stage history stable under bounded status history | backend-dev | done |
| Bound queue-owned training cancellation history like the monitor | backend-dev | done |
| Keep recorded metrics when the final TensorBoard read fails at completion | backend-dev | done |
| Keep recorded metrics when the final event file has no completed epoch | backend-dev | done |
| Empty-message and indeterminate UI states | ui | done |
| Readable unknown-status badges and announced terminal states | ui | done |
| Expose determinate progress as a percentage to screen readers | ui | done |
| Keep dashboard progress polls out of live regions; announce refresh warnings | ui | done |
| State why single-event epochs do not set the remaining-time estimate | backend-dev | done |
| Regression and integration validation | backend-validation; ui-validation | complete on the lifecycle prerequisite; final AML integration remains a separate gate |

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
  Trimmed histories must not re-append dropped stages: repeated polls leave
  the history unchanged, and newer stages still appear. Queue-owned
  cancellation keeps the newest records and its summary within the same
  status-history budget.
- Subprocess tests that observe ordinary, non-flushing Python stdout/stderr
  before child completion, with inherited unbuffered mode explicitly unset
  in the test parent.
- UI helper tests plus lint/build and deterministic browser checks.
- Revalidate this prerequisite after rebasing onto the lifecycle prerequisite,
  then verify the final backend-neutral integration separately.

## Current evidence and baseline limitations

Rebased onto the current lifecycle prerequisite and main, the full core, API
and queue suite passed **1,344 tests** on Windows with HTTP blocked, with 34
skips (mostly POSIX-only descriptor cases) and the same 43 failures as the
lifecycle prerequisite. Each replayed commit showed no new failures when the
branch was first rebased; later rebases onto the prerequisite's review fixes
replayed the same patches unchanged. With the
lifecycle plan's verification-only POSIX emulation it passed **1,384 tests**,
again with only the prerequisite's three failures. Workflow-streaming tests
pass, and the prediction-workflow tests match main: 18 pass and four fail on
this host's mismatched PROJ database. All 47 UI unit-test files (356 cases,
including the active-jobs and job-progress commands), the production build
and targeted lint pass. The installed UI dependencies predate main's
lockfile patch updates to build tooling, so an exact-lockfile build was not
rerun locally.

Focused backend tests and the UI status helper cases pass. Browser checks
exercise queued, unknown-progress, determinate, terminal, unknown-status,
empty-message, legacy-record, and reduced-motion behavior. They also check
terminal badge colors, that the status region stays mounted while excluding
active progress, and that a progress bar exposes its percentage under a name
made of its message and step. A separate check mounts the real dashboard
list against a routed API with fake timers: no live region wraps its
progress bars, and a failed refresh raises an alert. The production UI build
passed with the exact locked dependencies before the rebase.

Full UI lint reports findings in unchanged files; all changed UI files pass
targeted lint. These baseline issues are not silently fixed, suppressed, or
represented as a green full-suite result by this prerequisite.

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
