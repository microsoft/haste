# ADR-0005: Produce Prediction Attributes with Predictions

**Contents:** [Context](#context) - [Options](#options) -
[Decision](#decision) - [Consequences](#consequences)

**Status:** accepted
**Date:** 2026-09-06
**Decision basis:** User-directed decomposition of #183 and #136.

## Context

Both workflows need the same complete footprint results view. #183 establishes
one geometry archive per image layer. #136 demonstrates vector rendering with
a prediction-attribute sidecar but generates missing results through another
queue after the user opens the viewer.

## Options

| Option | Trade-off |
|---|---|
| First-open queued preparation | More queue/state machinery and a delayed first result |
| Inline preparation on a GET | Makes reads expensive, mutable, and retry-sensitive |
| Generate attributes with predictions | Adds producer work, but completion owns artifact readiness |

## Decision

Choose eager production: interactive prediction saves write attributes with
their GeoPackage; standard inference emits attributes in its existing job.
Both publish matching metadata. Results reads only load artifacts.

Use a per-model `prediction_results` metadata document as the authoritative
generation record and mirror result fields onto `Model` for compatibility.
Existing unrelated writers can save full Model snapshots; treating those
snapshots as publication authority could resurrect superseded results.
Serialize participating result publishers with renewable Blob leases (or a
filesystem lock for local metadata), not an assumed global metadata CAS.

Retain #183's layer-footprint queue. Do not add #136's prediction-edit-prep
queue, its configuration/trigger, or a first-open enqueue API.

## Consequences

Deploy the changed inference image with the backend. Legacy results need an
explicit rerun to gain attributes; opening them does not start a migration.
Versioned editing builds on the same attribute utility and writes its own
matching sidecar while saving a version.
Cloud publishers need access to the existing lease-storage account/container;
no new queue is added. Unreferenced immutable generation artifacts can remain
after failures or supersession; garbage collection is a separate concern.
