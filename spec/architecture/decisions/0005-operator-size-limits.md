# ADR-0005: Operator-Owned Size Limits

**Status:** accepted
**Date:** 2026-09-17
**Deciders:** HASTE maintainers

## Context

Operators need to tune ingestion caps without rebuilding applications. ARM
deployment replaces the Function App settings collection, so omitting a cap
from Bicep does not preserve an out-of-band override.

## Options Considered

### Runtime-Only Overrides

- Fast to apply, but subsequent infrastructure deployment removes the values.
- Independent dispatch inputs drift from the desired deployment configuration.

### GitHub Environment Configuration Variables

- Both deployment and lightweight updates use the same desired values.
- Local infrastructure deployments must explicitly synchronize those values.

## Decision

Use the three GitHub Environment configuration variables as the source of truth
for Actions. Both workflows resolve sizes through the same standard-library
Python parser. Missing or blank values restore defaults, not previous overrides.
Bicep declares bounded integer parameters and writes each setting only to its
consuming app. Local `azd` environments use the same names with decimal bytes.

### Components Affected

| Component | Path | Change |
|---|---|---|
| Workflows | `.github/workflows/` | Share variables and environment concurrency group |
| Deployment scripts | `.github/scripts/` | Resolve and validate all caps before writes |
| Infrastructure | `infra/` | Explicit bounded parameters and app-specific settings |
| Operations guide | `docs/configuration.md` | Apply, reset, rollback and local synchronization |

### Azure Services Affected

| Service | Change |
|---|---|
| Function Apps | Store the desired caps and recycle after settings changes |
| Azure Batch | New imagery tasks capture the queues worker's download cap |

## Consequences

- Editing a GitHub variable alone does not update Azure; an operator runs the
  update or deployment workflow.
- Actions serialize settings changes per environment; local deployments must
  still be coordinated with operators.
- HTTP checks are samples, not proof of queue-worker or Batch enforcement.
- Existing Batch tasks keep their submitted values. No tasks are cancelled.
- No automatic cross-app rollback; run output records previous values for
  operator recovery after a partial failure.
- Docker Compose retains its existing environment-variable configuration.

See [configuration](../../../docs/configuration.md#ingestion-size-limits) and
the [controls design](../../features/gdal-compensating-controls/design.md).