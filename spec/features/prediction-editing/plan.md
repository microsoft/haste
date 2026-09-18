# Plan: Versioned Prediction Editing

## Implementation

| Task | Agent | Stories | Status |
|---|---|---|---|
| Define editor scope from final #136 design | `backend-dev` | PE-1 to PE-7 | complete |
| Add version models, save/resolution processors, and protected API | `backend-dev` | PE-1, PE-4 to PE-6 | complete |
| Preserve identity and override-aware report semantics | `gis` | PE-3, PE-4, PE-6 | complete |
| Adapt editor panel, interactions, versions, and report/download controls | `ui` | PE-1 to PE-7 | complete |
| Exercise version, failure, artifact and report contracts | `backend-validation` | PE-3 to PE-6 | complete |
| Exercise editor actions and responsive shared map | `ui-validation` | PE-1 to PE-7 | complete |
| Simplify painting and keyboard review, remove separate edit sessions, and support saved damage thresholds | `ui`, `backend-dev` | PE-1 to PE-4, PE-7 | complete |
| Correct Blob policy handling and save/lease diagnostics for deployed failures | `backend-dev` | PE-4 | implemented; regression-backed corrections, remote root cause not confirmed |
| Stage prediction GeoPackages locally instead of on Azure Files | `backend-dev` | PE-4 | implemented; telemetry confirms both Fiona transaction failures and `/data` staging; remote post-deployment confirmation still required |

## Delivery

Create this branch from the common-results PR head only after that stage is
ready. Open a separate stacked PR targeting the common-results branch.
Keep the live local stack and saved project data untouched.

Base: the simplified [#200](https://github.com/microsoft/haste/pull/200) at
`1a18875`. History and save coordination stay on Model; the discarded raw
authority/reservation framework is not moved into this PR.

Restacked on 2026-09-13 after #200 moved onto refreshed #183. Preserve the
Model-backed simplification and review fixes from the old integration merges.
Application/runtime files remain identical to the pre-rebase `a0bb20b` tip,
including Blob-policy diagnostics and instance-local GeoPackage staging.
The maintained imagery runtime and ACR compatibility fixes now originate in
#183 rather than only this top PR. Their duplicate commits were dropped while
restacking; the final application/runtime tree remains unchanged.

## Shared-results integration: 2026-09-18

The common-results base now owns the model-row readiness projection, shared
Results actions, and strict HTTP-range PMTiles loader. This branch extends
`model_view` with the latest current-generation edited source and retains its
version metadata on every project/layer/model-list response.

Versioned downloads and both report dialogs live in the shared Results menu.
Keep the existing download chooser and revision-pinned requests; do not add a
metadata preflight before the chooser's own reads. Raw and saved artifact URLs
and filenames are resolved from one model snapshot.

Threshold/classification/version contracts and optional fingerprint plumbing
remain available. Prediction writers, stored version history, and local
GeoPackage staging are unchanged.

Validation: 167 backend/API/version/report tests, 80 raw-producer/queue tests,
and 329 UI tests passed. The production UI build and scoped lint across 54
changed UI files passed. The row-route regressions cover latest
current-generation edits even when raw output is unavailable, and raw/saved
downloads keep their URL and filename tied to one model read. No deployed
range verification, service restart, or project-data changes were performed.
