# Building Validation configuration

**Status:** in-progress
**Type:** feature
**Author:** calebrob6
**Date:** 2026-08-22
**Priority:** P2

## Summary

Lets a user choose how many building footprints the Building Validation
workflow asks them to label, instead of the hardcoded 200. A gear icon beside
the Building Validation **Launch** button — and a matching one inside the
validation view — opens a small modal holding the setting. The same modal
carries the first UI affordance for clearing validation labels.

## Motivation

The sample size is hardcoded at the call site:

```js
// ui/src/Components/BuildingValidation/BuildingValidation.jsx
`GetBuildingFootprintsGeoJSON?projectId=${projectId}&imageLayerId=${imageLayerId}&sample=200`
```

200 is a reasonable default but it is not right for every layer. A dense urban
scene may warrant more; a quick spot-check may warrant fewer. Analysts
currently have no way to change it, and the accuracy figures in the Validation
and Assessment reports are only as good as the sample the analyst was given.

There is also no way to clear validation labels from the UI at all, which makes
any "start over" request unserviceable.

## Success Criteria

- [ ] The number of footprints to validate is user-configurable per image
      layer, defaulting to 200.
- [ ] Raising the count preserves every building already sampled and adds only
      the difference — a user never loses labeling work by asking for more.
- [ ] Lowering the count while labels exist is refused with an explanation
      rather than silently discarding labeled buildings.
- [ ] Validation labels can be cleared from the UI, behind a confirmation.
- [ ] Saving validation labels cannot reset the configured count.

## HASTE Components Affected

| Component | Impact |
|---|---|
| `hastelib/src/hastegeo/core/models/` | `sampleSize` added to `BuildingValidation`. |
| `hastelib/src/hastegeo/core/utils/` | New deterministic `sample_indices` helper in `footprints.py`. |
| `api/hastefuncapi/` | `GetBuildingFootprintsGeoJSON` uses the helper; `PutBuildingValidation` preserves `sampleSize`; new `PutBuildingValidationConfig`. |
| `ui/src/Components/` | New `ValidationConfigModal`; gear entry points in `LayerRow` and `BuildingValidation`; clear control in `BuildingValidationRightPanel`. |

## Related Specs

None. The Interactive Labeler's label-restore work
([PR #135](https://github.com/microsoft/haste/pull/135)) is not a dependency,
but its root cause — a wholesale document replace dropping fields the client
didn't send — is the same hazard this feature has to avoid, and is called out
in [design.md](design.md).

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [plan.md](plan.md) | Execution plan, phases | implemented |
| [impact-analysis.md](impact-analysis.md) | Risk, dependencies, blast radius | draft |
| [user-stories.md](user-stories.md) | User stories & acceptance criteria | draft |
| [design.md](design.md) | Technical design & API contracts | draft |
| [data-model.md](data-model.md) | Schema changes | draft |
| [test-plan.md](test-plan.md) | Test strategy & coverage | draft |
| [rollout.md](rollout.md) | Rollout & rollback | draft |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-22 | Store `sampleSize` on the layer-scoped `BuildingValidation` document rather than on `ImageLayer`. | It governs the labels in that document, is read by the same `GetBuildingValidation` call the validation view already makes on load, and needs no new metadata type. |
| 2026-08-22 | Do not persist the sampled building ids. | The existing fixed-seed sample is a permutation prefix, so a larger count provably contains the smaller one. Storing ids would add a second source of truth for no gain. See [design.md](design.md#why-growing-the-sample-is-free). |
| 2026-08-22 | Enforce the count-change rules server-side, with the client mirroring them. | Validation labels are layer-scoped and shared last-write-wins, so two users can race; only the server sees the authoritative label set. |
| 2026-08-22 | Clearing labels reuses `PutBuildingValidation` with `labels: {}`. | The `sampleSize`-preserving merge makes a dedicated delete route unnecessary. |
| 2026-08-22 | Cap the modal at 2000. | Matches the server-side clamp in `GetBuildingFootprintsGeoJSON`; a higher number would silently not be honored. |
