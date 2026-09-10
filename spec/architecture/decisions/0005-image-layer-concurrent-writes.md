# ADR 0005: Preserve Concurrent Image-Layer Updates

## Status

Accepted for the review corrections in #183.

## Context

Imagery processing and footprint tiling update different fields on the same
ImageLayer document. Reading, merging and unconditionally overwriting that
document can lose another worker's progress, despite excluding its fields
from the submitted update.

## Decision

Use atomic top-level JSON merges for ImageLayer metadata saves. Blob and ADLS
use conditional ETag writes with bounded conflict retries; Cosmos uses
conditional replacement; PostgreSQL merges JSONB within its upsert; local
storage serializes writes with a process-level file lock and atomic replacement.
Other metadata types retain their existing behavior.

Footprint task output fields are server-owned. Public layer edits omit them;
artifact reads validate the exact owning project/layer archive namespace.

Footprint requests derive a unique job and task identity from the persisted
request ID. Batch adopts an existing task; local execution uses a task lock and
a stable container name to recover a container after worker interruption.
Terminal metadata must be saved before best-effort task cleanup.

## Consequences

Disjoint updates no longer overwrite each other. This is not a global metadata
transaction or a new result-lifecycle store. Writers of the same field still
need domain-specific ordering, and repeated storage failures still propagate.

The Functions queue host permits five deliveries, with the existing 30-second
retry visibility delay. This setting applies to every queue trigger in that
host; footprint failures propagate rather than being acknowledged on the first
transient storage or Batch error. Exhausted deliveries still enter the poison
queue and require operator recovery. No historical layers are backfilled.
