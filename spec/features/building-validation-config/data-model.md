# Data Model: Building Validation configuration

## Changed: `BuildingValidation`

`hastelib/src/hastegeo/core/models/projects.py`

One additive field. Stored via `MetadataProcessor` under the `VALIDATION`
metadata type, partitioned by `projectId`, keyed by `imageLayerId`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `imageLayerId` | `str \| None` | `None` | unchanged |
| `projectId` | `str \| None` | `None` | unchanged |
| `labels` | `dict` | `{}` | unchanged — Overture id → `ValidationLabel` |
| **`sampleSize`** | **`int \| None`** | **`200`** | **new** — how many footprints the validation set draws |
| `dependsOn` | `tuple[str, str]` | `("ImageLayer", "imageLayerId")` | unchanged |

### Example document

```json
{
  "imageLayerId": "…",
  "projectId": "…",
  "sampleSize": 300,
  "labels": {
    "08b2…": { "id": "08b2…", "label": "Damaged", "updatedAt": "2026-08-22T…" }
  },
  "dependsOn": ["ImageLayer", "imageLayerId"]
}
```

## Migration

None required. Documents written before this change have no `sampleSize`, and
Pydantic fills the default `200` on read — which is exactly the behavior those
layers had when the value was hardcoded. The first config save materializes the
field.

## Write paths

| Path | Writes `labels` | Writes `sampleSize` |
|---|---|---|
| `PutBuildingValidation` (label save, clear) | yes | **no — preserves the stored value** |
| `PutBuildingValidationConfig` (config save) | no | yes |

Keeping the two write paths disjoint is what stops a label save from resetting
the count. The preservation is not incidental: `BuildingValidation(**req_body)`
would otherwise coerce a missing `sampleSize` to the default `200`, so
`PutBuildingValidation` reads the stored document and carries the value across
explicitly.

## What is deliberately *not* stored

The ids of the sampled buildings. The sample is reproducible from
`(footprints .gpkg, seed 42, sampleSize)`, and the seeded draw is a permutation
prefix, so a larger `sampleSize` provably contains the smaller draw. Persisting
the ids would create a second source of truth that could disagree with what the
endpoint actually returns.

The trade-off is that the sample is only stable while the layer's footprints
file is unchanged; re-ingesting footprints reshuffles it. That is pre-existing
behavior, not introduced here.
