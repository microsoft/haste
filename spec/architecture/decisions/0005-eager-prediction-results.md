# ADR-0005: Produce Prediction Attributes with Predictions

**Contents:** [Context](#context) - [Options](#options) -
[Decision](#decision) - [Consequences](#consequences)

**Status:** accepted
**Date:** 2026-09-06
**Decision basis:** Keep prediction production responsible for result readiness.

## Context

Standard inference and interactive labeling need the same footprint results
view. Geometry is shared in one archive per image layer; model-specific
attributes supply the classes and scores used to color those footprints.
The attribute sidecar must match the prediction GeoPackage and be available
when prediction production completes.

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

Keep result pointers and output identity on `Model`, using existing metadata
and artifact storage. A separate authority/mirror and raw-result locking
framework were rejected during review as unnecessary scope for this feature.

Retain the existing layer-footprint queue. Do not add a separate
prediction-preparation queue, trigger, or first-open enqueue API.

## Consequences

Deploy the changed inference image with the backend. Legacy results need an
explicit rerun to gain attributes; opening them does not start a migration.
Versioned editing builds on the same attribute utility and writes its own
matching sidecar while saving a version.
No new raw-result metadata collection, lease permissions, or queue is required.
