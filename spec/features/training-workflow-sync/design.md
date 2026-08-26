# Design — Polygon training workflow sync

## 1. Label class contract

`labels.classes` comes from the project's `primaryClasses`, which the UI lets a
user pick from a catalog in any order and which `PrimaryClass.name` does not
constrain to any vocabulary. Mask values are `index + 1`; **0 is reserved for
"not labeled"** and is never a target.

Three separate rules act on that list. They are checked before a job is
submitted, not left to fail inside the container.

| Rule | Why | Enforced by |
|---|---|---|
| Names match ignoring case and separators | `PrimaryClass.name` is a free string, and the `PutProject` docstring's own example uses `no_damage` | `normalize_class_name` |
| `Damaged Building` must be class value **3** | `merge_with_building_footprints.py` counts raster value 3 for the damage fraction and `inference.py` paints it red | `resolve_constraint_indices` |
| `No Damage` must be the **last** class | It is given no output channel, which only works if it is the final mask value | `resolve_constraint_indices` |

`No Damage` last rules out the UI catalog's own order, where `Flood Extent`
follows it. `should_use_constraint_loss` declines that layout and logs why,
rather than generating a config `fine_tune.py` would reject at startup.

> The rules are implemented twice — `hastegeo.core.utils.label_classes` for the
> submit side and `bda/config.py` for the container. This is deliberate: `bda/`
> is a vendored fork that has to run standalone. Both files carry a note. Drift
> between them means submitting jobs that fail on startup, so they are checked
> against each other in review.

## 2. The "No Damage" constraint loss

### What the label means

A "No Damage" annotation says *this building is not damaged*. It does not say
what the pixels look like — "No Damage" is not a visual class. So it cannot be
trained as an ordinary hard segmentation target, and it must never appear in a
prediction.

### Output channel layout

With the constraint loss on, `num_classes = len(classes)` rather than
`len(classes) + 1`:

```
classes = [Background, Building, Damaged Building, Cloud, No Damage]
mask values      1           2            3          4       5
channels    0    1           2            3          4       —
            ^ Unlabeled: emitted, never supervised   ^ No Damage: no channel
```

`no_damage_index == num_channels` is asserted by `supervised_logits()`, which
returns `y_hat[:, 1:]`.

### The objective

```
CE over labeled pixels except "No Damage", against targets shifted down by one
  + mean p(Damaged Building) at "No Damage" pixels
```

The softmax runs over the *supervised* logits only, so neither the unlabeled
channel nor "No Damage" can absorb probability mass.

**Why this shape.** An earlier form kept every channel and penalized only
`p(Damaged Building)`. That is under-constrained: dumping all mass on the
unsupervised "No Damage" channel drives the penalty to zero at no cost. Fitting
raw logits against it leaves the non-damaged channels at a dead-even split, and
predicting "No Damage" there costs the same as predicting Background to six
decimal places. A real network turns that channel into a detector for exactly
those pixels — which is what dev observed.

### Consequences elsewhere

| Site | Consequence |
|---|---|
| `validation_step` / `test_step` | Must be overridden. The base implementations hand "No Damage" targets to a criterion with no channel for them. |
| Metrics | Take the predictions inference would emit, not raw logits — otherwise channel 0 can win the argmax and be scored as a prediction the deployed model cannot make. Targets fold "No Damage" into the ignored class. |
| `inference.py` | Argmax over channels `1:` and shift back onto 1-based mask values. Upstream does not do this; without it the unsupervised channel 0 can win. |

## 3. Cluster-based label creation

Opt-in via `labels.cluster_size_in_meters`. A grid of that cell size is laid
over the labels and one image/mask pair is emitted per populated cell; cells
below `labels.min_pixels_per_cluster` (default 1000) are discarded.

- Features are assigned to **every cell they intersect**, so a polygon
  straddling a boundary appears in both, clipped by each cell's raster extent.
- Cell geometry is clipped to the overall label extent, so edge cells do not
  request imagery outside the labeled area.
- Assignment queries a `shapely.STRtree`. A full scan per cell is
  O(cells × features) — 110.5s versus 0.52s on 3000 buildings over 30 km² at a
  500 m cell size, identical output.
- Omitting the key preserves the previous behavior exactly: same filenames,
  same single pair.

### CRS constraint

The grid is built in the **imagery's own coordinate units**, so
`cluster_size_in_meters` only means metres on a projected CRS. On a geographic
one a 1000 "metre" cell is 1000 degrees and every label collapses into a single
cluster — a silent no-op, which is the worst failure mode. Clustering therefore
**fails fast** on a geographic or missing CRS.

Nothing upstream guarantees a projected CRS: there is no `is_projected` check
in the ingest path, `_create_mosaic_cog` preserves the source projection, and
`merge_with_building_footprints.py` carries a geographic-CRS UTM fallback for
rasters of the same lineage. `buffer_in_meters` has the identical latent hazard
and is deliberately left alone — it is pre-existing and already noted in the
module docstring.

### Failure handling

Only one condition is skippable: a cell whose crop geometry misses the raster,
raised as `CropGeometryOutsideRasterError`. Everything else — a channel-count
mismatch, a failed GDAL call — aborts the run. A broad `except ValueError`
would swallow real configuration errors once per cluster and then blame the
cluster sizing.

`--overwrite` clears the image's prior pairs first, so a stale `_cluster_N`
from an earlier cluster size cannot join a later training set;
`SegmentationDataModule` loads every TIFF in `images/`.

## 4. Mask rasterization CRS

All classes are burned from the **CRS-warped** label file. Previously the first
class used the warped file and classes 2..N the original EPSG:4326 one, relying
on `gdal_rasterize` reprojecting on the fly. Where it does not, those polygons
land outside a projected raster's extent and are silently dropped, leaving
masks of `{0, 1}` — [upstream measured exactly that][pr20].

This did **not** reproduce on GDAL 3.4.1 locally, and the training image pins
`gdal<3.9`, so whether HASTE was ever affected is unconfirmed. Reading from the
file already in the target CRS removes the dependency either way.

[pr20]: https://github.com/microsoft/building-damage-assessment/pull/20

## 5. Configuration contracts

New keys, all optional and all defaulting to previous behavior:

| Key | Type | Default | Notes |
|---|---|---|---|
| `labels.cluster_size_in_meters` | float > 0 | `null` | `null` disables clustering |
| `labels.min_pixels_per_cluster` | int ≥ 0 | 1000 | 0 keeps every cluster |
| `training.gpu_ids` | list[int ≥ 0] | `null` | Overrides `training.gpu_id`; >1 selects DDP |
| `training.preload` | bool | `true` | Tiles into RAM; scales per DDP process |
| `training.use_constraint_loss` | bool | derived | Set by `train.py` from the class list |

Validation happens in two passes: `_validate_optional_config` type-checks the
keys that are present, and `_validate_optional_values` range-checks them, so a
hand-edited `cluster_size_in_meters: 0` is rejected by name rather than
surfacing as a `ZeroDivisionError` inside `np.arange`. The Pydantic model
carries matching `gt`/`ge` constraints for the API path.

## 6. Deliberate deviations from upstream

| Upstream | Here | Why |
|---|---|---|
| Hardcodes `precision="bf16-mixed"` | Runtime `torch.cuda.is_bf16_supported()` | T4 pools are Turing; CPU fallback must stay fp32 |
| Drops `log_dict(train_metrics)` | Kept | `tbparser` reads `train_MulticlassAccuracy` |
| No inference-side channel handling | Argmax excludes channel 0 | Otherwise the unsupervised channel can win |
| `assert subprocess.call(...) == 0` | `subprocess.run` with captured stderr | Pre-existing HASTE hardening |
| Broad `except ValueError` on the cluster skip | `CropGeometryOutsideRasterError` | Not swallowing real errors per cluster |
| `configure_losses()` override | Not ported | Adds a `dice` branch this repo never uses; `torchgeo` is pinned here and unpinned upstream |

## 7. Large raster outputs

The cropped training image and buffered mask can exceed the classic TIFF
4 GiB limit when labels span a large, high-resolution aerial scene.
`rasterio.DatasetReader.profile` preserves raster metadata but not the
source dataset's BigTIFF creation option, so derived writes must apply it
explicitly.

Both rasterio write paths go through one helper that copies the source
profile and sets `BIGTIFF=IF_SAFER`. Copying avoids mutating a profile that a
caller may reuse. `IF_SAFER` lets GDAL retain classic TIFF for small outputs
while selecting BigTIFF when the uncompressed result could exceed 4 GiB.

The raw mask is created by `gdal_rasterize` and already uses
`BIGTIFF=YES`. This change aligns the surrounding rasterio writes without
changing CRS, transform, dimensions, compression, tiling, nodata, or dtype.
