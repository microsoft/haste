# User Stories: Project Loading Performance

## Stories

### US-001: Reproducible Measurement

As a maintainer, I need reproducible project-load measurements before changing
the loading path. Report logical metadata operation counts, payload bytes, and
wall-clock timings separately. Synthetic local replay and HTTP measurements must
identify their fixture and storage backend; neither estimates network round trips.

### US-002: Bounded Backend Reads

As an analyst, I need projects with many layers and models to load efficiently.
Use exact metadata-type and partition filtering, bound shared I/O concurrency,
and preserve missing-key behavior across storage backends.

### US-003: Responsive Project Details

As an analyst, I need equivalent project detail data without per-layer repeated
partition reads. Preserve legacy payload fields, support conditional reads, and
ensure an explicit mutation refresh can obtain current data.

### US-004: Predictable Frontend Loading

As an analyst, I need visible, recoverable route loading and non-overlapping
background polling. Stop polling terminal jobs, report successful training
correctly, and avoid forced reloads when an edit modal is canceled.

## Agent Assignment Map

| Story | Implementing Agent | Validating Agent |
|---|---|---|
| US-001 | backend-dev, ui | backend-validation, ui-validation |
| US-002 | backend-dev | backend-validation |
| US-003 | backend-dev | backend-validation |
| US-004 | ui | ui-validation |