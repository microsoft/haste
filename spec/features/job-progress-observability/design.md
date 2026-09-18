# Design: shared job progress and workflow observability

## Contents

- [Scope](#scope)
- [Output discovery](#output-discovery)
- [Shared progress processing](#shared-progress-processing)
- [Workflow logs](#workflow-logs)
- [UI](#ui)
- [Compatibility](#compatibility)

## Scope

Reuse TensorBoard event files and `logs/workflow_progress.log` for every
backend. No local-only progress format, new polling transport, training
parameter change, or loss/data transformation is introduced.

## Output discovery

Local reads open the configured work root as the trust anchor and traverse
job/task ancestry through directory descriptors without following symlinks.
The exact requested file takes precedence over a unique nested suffix match,
then a unique basename-prefix match for generated names such as TensorBoard
events. Ambiguous matches produce an explicit unavailable-telemetry
diagnostic, never an arbitrary result or cross-job search.

Discovery and the final no-follow open retain the task descriptor. Compare
the opened file's device/inode with the discovered regular file and return
an owned binary stream, not a resolved pathname for a caller to reopen.
Text reads and deferred chunk consumption use that same open file, so
replacing a job/task directory or output pathname cannot redirect the read.
Reject symlinked work roots, job/task ancestors, and matching output files;
do not descend into symlinked directories during discovery.

This local-worker read contract requires POSIX descriptor-relative APIs.
Native Windows raises an explicit unsupported-platform error; there is no
path-based fallback. Windows hosts can run the real worker in Linux Docker,
but filesystem race regressions must execute on Linux, not with mocked
descriptor behavior.

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
streams while each step runs. Set `PYTHONUNBUFFERED=1` in a copy of the child
environment so ordinary Python `print` calls remain visible on non-TTY
streams; preserve command arguments and the parent environment.
The parent records stage boundaries and nonzero exits in the existing
workflow log. It does not retain an unbounded copy of child output or
suppress successful child output until exit.

Training terminal polling appends all valid workflow stage records before
failure/cancellation summaries and cleanup, including jobs that finish
before their first poll. Direct and queue-owned training cancellation read
the final history after stopping the task and before cleanup, using the same
optional-telemetry reader and history parser as terminal polling.
Deduplicate by the complete timestamped record, not message substrings, so
repeated stages at different times remain visible. Preserve terminal
execution status, existing user-safe error details, and deferred, fenced
cleanup. Unavailable history cannot prevent committing a provider-confirmed
cancellation; a too-late cancellation retains the provider's actual
terminal state.

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

Backend-neutral integration must carry forward the stream-owning local
output reader rather than reintroducing a path resolver. Its terminal and
cancellation orchestration must collect workflow history before committing
terminal messages and releasing outputs; do not move cleanup ahead of the
existing metadata fence.
