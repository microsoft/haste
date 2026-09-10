# Plan: shared job progress

## Tasks

| Task | Agent | Status |
|---|---|---|
| Safe job-scoped output discovery | backend-dev | done |
| Partial/empty/non-finite TensorBoard handling | backend-dev | done |
| Shared running/terminal progress updates | backend-dev | done |
| Live subprocess streams and stage messages | backend-dev | done |
| Empty-message and indeterminate UI states | ui | done |
| Regression and integration validation | backend-validation; ui-validation | complete on the lifecycle prerequisite; final AML integration remains a separate gate |

## Validation

- Unit tests for exact/nested/prefix discovery, ambiguity, missing files,
  and traversal/symlink boundaries.
- Real TensorBoard fixtures for empty and growing event files, epoch zero,
  missing/non-finite metrics, and completed versus running epoch counts.
- Processor tests for successful completion without telemetry and running
  polling before metrics are available.
- Subprocess tests that observe stdout/stderr before child completion.
- UI helper tests plus lint/build and deterministic browser checks.
- Revalidate this prerequisite after rebasing onto the lifecycle prerequisite,
  then verify the final backend-neutral integration separately.

## Current evidence and baseline limitations

Focused backend tests and the UI status helper cases pass. Browser checks
exercise queued, unknown-progress, determinate, terminal, empty-message,
legacy-record, and reduced-motion behavior. The production UI build passes
with the exact locked dependencies.

The full library run has one unchanged baseline failure:
`test_artifacts.py::test_zip` calls the nonexistent `ArtifactProcessor.zip`
method. Full UI lint also reports findings in unchanged files; all changed
UI files pass targeted lint. These baseline issues are not silently fixed,
suppressed, or represented as a green full-suite result by this prerequisite.
