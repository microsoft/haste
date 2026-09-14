# Shared job progress and workflow observability

**Status:** implemented

Make local and remote runs use the same existing TensorBoard and workflow-log
reporting path. Correct output discovery, incomplete telemetry handling,
terminal progress, live subprocess logs, and status presentation without
changing model training semantics.

This concern is integrated with the local lifecycle and backend-neutral/AML
work for live validation. Any later PR separation must preserve the shared
reporting path and the verified in-flight behavior.

## Documents

- [Design](design.md)
- [User stories and agent assignments](user-stories.md)
- [Implementation plan and validation](plan.md)
