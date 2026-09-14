# Design: shared job progress and workflow observability

## Scope

Reuse TensorBoard event files and `logs/workflow_progress.log` for every
backend. No local-only progress format, new polling transport, training
parameter change, or loss/data transformation is introduced.

## Output discovery

Local reads first resolve the exact requested path within the task directory.
If absent, find a unique nested suffix match, then a unique basename-prefix
match for generated names such as TensorBoard events. All discovery stays
inside that execution's workspace, including symlink resolution.
Ambiguous matches produce an explicit unavailable-telemetry diagnostic,
never an arbitrary result or cross-job search.

## Shared progress processing

The existing TensorBoard parser remains authoritative for recorded epochs,
accuracy, and training loss. Empty or partially written files are normal
while a job starts. Missing telemetry must not change execution status or
cause integer conversion of unset counters.

Keep non-finite metric values unavailable in the API representation and log
the condition; never substitute zero or modify the original event file.
Only estimate remaining time after a completed epoch provides a usable
duration. Recorded zero elapsed time is valid, not a missing-value sentinel.

Business completion sets terminal progress independently of event-file
availability. A failed or cancelled job does not become successful merely
because its percentage or logs suggest completion.

## Workflow logs

Subprocess stdout and stderr flow directly to the backend's existing output
streams while each step runs. The parent records stage boundaries and
nonzero exits in the existing workflow log. It does not retain an unbounded
copy of child output or suppress successful child output until exit.

## UI

Use the existing project/home polling. Display valid states even when the
message list is empty. Render unknown progress as indeterminate rather than
inventing a percentage; show terminal status regardless of missing counters.
Keep FluentUI, current styling, and old-record compatibility.

## Compatibility

The prerequisite uses existing `BaseRunner` and job-model interfaces and has
no dependency on AML types or SDKs. The later backend-neutral integration
must preserve these read/progress semantics. Training budgets, labels,
checkpoints, and raw TensorBoard metrics remain unchanged.
