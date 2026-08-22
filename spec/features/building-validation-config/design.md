# Technical Design: Building Validation configuration

## Overview

One new persisted field (`sampleSize`), one new pure helper that makes the
existing sampling behavior explicit, one new endpoint that enforces the
count-change rules, and a modal reachable from two places. No new artifact, no
change to the footprints GeoPackage, no re-embed.

## Architecture

```
┌────────────────────────────┐
│ LayerRow (gear)            │
│ BuildingValidation (gear)  │
└─────────────┬──────────────┘
              │ opens
┌─────────────▼──────────────┐   GET  GetBuildingValidation        ┌──────────┐
│ ValidationConfigModal      │──────────────────────────────────▶ │ Cosmos   │
│  • sampleSize field        │   PUT  PutBuildingValidationConfig  │ (VALIDA- │
│  • Clear labels (confirm)  │   PUT  PutBuildingValidation {}     │  TION)   │
└─────────────┬──────────────┘                                     └──────────┘
              │ on save, validation view re-fetches
┌─────────────▼──────────────────────────────┐
│ GetBuildingFootprintsGeoJSON?sample=N      │
│   └─ footprints.sample_indices(rows, N)    │──▶ buildingFootprintsUrl (.gpkg)
└────────────────────────────────────────────┘
```

## Why growing the sample is free

`GetBuildingFootprintsGeoJSON` already samples deterministically:

```python
gdf = gdf.sample(n=sample_size, random_state=42)
```

`DataFrame.sample` calls `RandomState(42).choice(n_rows, k, replace=False)`,
which NumPy's legacy generator implements as `permutation(n_rows)[:k]`. The
draw for `k = 200` is therefore a **strict prefix** of the draw for `k = 300`.
Confirmed against the versions this repo pins:

```
RandomState(42).choice(5000, 200) == RandomState(42).choice(5000, 300)[:200]  → True
```

Consequences:

- Raising the count returns a superset. Every building the analyst has already
  seen and labeled is still in the set, in the same position, and the newly
  added buildings are exactly "the difference".
- Nothing needs to be stored to achieve that — not the drawn ids, not a cursor.
- Lowering the count truncates the prefix, which is why it is only safe when no
  labels exist.

That behavior is an implementation detail of NumPy rather than a documented
API contract, so it is not left implicit. `sample_indices` computes the
permutation prefix itself and a unit test asserts the nesting property
directly, so a NumPy change breaks a fast offline test rather than silently
reshuffling users' validation sets.

**Limitation (pre-existing, documented not fixed):** the prefix property holds
only while the layer's footprints `.gpkg` is unchanged. Re-ingesting footprints
changes the row count and order, which reshuffles the sample. That is already
true of today's hardcoded 200.

## New components

| Component | Path | Responsibility | Technology |
|---|---|---|---|
| `sample_indices` | `hastelib/src/hastegeo/core/utils/footprints.py` | Deterministic permutation-prefix row selection + clamp | Python |
| `PutBuildingValidationConfig` | `api/hastefuncapi/function_app.py` | Enforce the count-change rules, persist `sampleSize` | Azure Functions |
| `ValidationConfigModal` | `ui/src/Components/BuildingValidation/ValidationConfigModal.jsx` | The modal | React / FluentUI |
| `validationConfig.js` | `ui/src/Components/BuildingValidation/validationConfig.js` | Pure count-change rule, testable without a browser | JS |

## Modified components

| Component | Change |
|---|---|
| `models/projects.py` `BuildingValidation` | `sampleSize: Optional[int] = 200`. |
| `GetBuildingFootprintsGeoJSON` | Uses `sample_indices` instead of the inline `gdf.sample`. Behavior identical at the default. |
| `PutBuildingValidation` | Preserves the stored `sampleSize` when the payload omits it. |
| `LayerRow.jsx` | Gear button beside **Launch**. |
| `BuildingValidation.jsx` | Reads `sampleSize` from `GetBuildingValidation`; gear button; re-fetch in place on save. |
| `BuildingValidationRightPanel.jsx` | Clear-labels control behind a confirm. |

## The data-loss hazard this design must avoid

`PutBuildingValidation` replaces the stored document wholesale:

```python
MetadataProcessor(...).save(validation.imageLayerId, validation.model_dump())
```

and the validation view sends only what it holds:

```js
await apiPut("PutBuildingValidation", { projectId, imageLayerId, labels });
```

Adding `sampleSize` to that model without further change means
`BuildingValidation(**req_body)` fills it with the **default 200**, and every
label save silently resets the user's configured count. This is the same
failure mode as the Interactive Labeler bug in
[PR #135](https://github.com/microsoft/haste/pull/135), where a wholesale
replace dropped everything the client hadn't hydrated.

`PutBuildingValidation` therefore loads the stored document first and keeps its
`sampleSize` whenever the request body does not explicitly carry one. A
regression test pins this.

## API design

### `PUT /api/PutBuildingValidationConfig`

**Auth:** `AUTH_LEVEL`

**Request:**

```json
{ "projectId": "...", "imageLayerId": "...", "sampleSize": 300 }
```

**Rules**, evaluated against the stored document:

| Condition | Response |
|---|---|
| `sampleSize` missing, non-integer, or outside `[1, 2000]` | `400` |
| `new == current` | `200`, no write |
| `new > current` | `200`, `sampleSize` updated. Existing sample retained, difference added |
| `new < current` and no labels stored | `200`, `sampleSize` updated |
| `new < current` and labels stored | `409` with a message naming the label count and directing the user to clear labels first |

**Response:** the updated `BuildingValidation` document.

`409` rather than `400`: the request is well-formed, it conflicts with stored
state, and it becomes valid once the labels are cleared.

### Unchanged contracts

`GetBuildingValidation` gains `sampleSize` in its response body — additive, so
existing clients are unaffected. `GetBuildingFootprintsGeoJSON` keeps its
`sample` query parameter and clamp.

## UI behavior

- The gear is disabled under the same condition as **Launch**
  (`!item.buildingFootprintsUrl`) — without footprints there is nothing to
  configure.
- The modal loads current state via `GetBuildingValidation` when it opens, so
  it never renders a stale count.
- The client evaluates the same rules through `canApplySampleSize` for
  immediate feedback; the server remains the authority and its `409` is
  surfaced verbatim if the two ever disagree.
- Saving from inside the validation view re-fetches footprints and re-renders
  in place. Labels held in component state are preserved; the buildings the
  user already labeled keep their labels because the new set is a superset.
- Clearing labels is a `PutBuildingValidation` with `labels: {}` behind an
  "are you sure" confirm, offered both in the modal and in the validation
  view's right panel.
