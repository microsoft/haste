# ADR-0006: Versioned Derived Prediction Artifacts

**Contents:** [Context](#context) - [Options](#options) -
[Decision](#decision) - [Consequences](#consequences)

**Status:** accepted
**Date:** 2026-09-06
**Design reference:** [#136](https://github.com/microsoft/haste/pull/136)

## Context

Analysts need to correct and compare model results without destroying the
original prediction. A versioned GeoPackage alone is insufficient because the
shared results map renders a columnar sidecar, not the GeoPackage directly.

## Options

| Option | Trade-off |
|---|---|
| Overwrite raw predictions | Simple pointer, but loses model provenance |
| Save only versioned GeoPackages | Preserves files, but cannot render correct per-version colors |
| Save paired version artifacts | More derived storage, with consistent maps and downloads |

## Decision

Save immutable numbered GeoPackages and matching sidecars together. Append
metadata only after both writes succeed. Preserve raw pointers and protect
existing versions from replacement.

Version selection is request-local, not a mutable shared model pointer.
Visualizer/reports default to latest edited; explicit zero requests raw.
Artifact downloads use explicit raw/version numbers. Reports allow independent
selection and count the analyst's effective class.

## Consequences

Reuse [the eager attribute utility](0005-eager-prediction-results.md). No extra
preparation queue or first-open generation is needed. Older artifacts missing
sidecars remain explicit compatibility states, not silently misrendered results.
