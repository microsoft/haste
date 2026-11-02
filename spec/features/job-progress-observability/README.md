# Shared job progress and workflow observability

**Status:** implemented

Make local and remote runs use the same existing TensorBoard and workflow-log
reporting path. Correct output discovery, incomplete telemetry handling,
terminal progress, live subprocess logs, and status presentation without
changing model training semantics.

This prerequisite follows local lifecycle/state fixes and remains independent
of the backend-neutral/AML feature that will be integrated above it.

## Documents

- [Design](design.md)
- [User stories and agent assignments](user-stories.md)
- [Implementation plan and validation](plan.md)
