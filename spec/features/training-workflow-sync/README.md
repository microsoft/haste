# Feature: Polygon training workflow sync

**Status:** in-review
**Author:** calebrob6
**Date:** 2026-08-21
**Target Release:** next training-image build
**Priority:** P1
**Work Item:** [PR #133](https://github.com/microsoft/haste/pull/133)

## Summary

The polygon-based training workflow under `docker/training/code/` was forked
from [microsoft/building-damage-assessment][bda] and the two drifted apart.
This brings across the newer `create_masks` / `fine_tune` / `inference` work —
cluster-based label creation, a corrected weakly-supervised "No Damage" loss,
multi-GPU training, and imagery channel handling — while keeping the hardening
that only exists here.

Two of the changes are correctness fixes rather than features: the "No Damage"
constraint loss was computing the wrong objective and could teach the model to
predict a class that does not visually exist, and mask rasterization depended
on GDAL reprojecting on the fly.

[bda]: https://github.com/microsoft/building-damage-assessment

## Motivation

- **Sparse labels wasted training capacity.** `create_masks.py` emitted a
  single image/mask pair spanning the full label extent. Where the labeled
  buildings are scattered across a large scene, that is one enormous,
  mostly-unlabeled tile.
- **The "No Damage" weak label was mishandled.** It was never enabled in
  practice (the processor never set the flag), and when enabled it hardcoded a
  class layout and left the model free to emit "No Damage" as a prediction —
  observed in dev.
- **Training was dataloader-bound.** Patch reads from compressed GeoTIFFs left
  the GPU at roughly half utilization.
- **Large aerial scenes exceeded classic TIFF limits.** Derived training
  images inherited the source profile without a BigTIFF creation option, so
  crops larger than 4 GiB failed during `create_masks.py`.

Without this, a project defining a **No Damage** class trains against a
silently wrong objective, and its damage reports cannot be trusted.

## Success Criteria

- [x] "No Damage" cannot appear in a prediction raster
- [x] The constraint loss derives its class indices from the project's classes
      rather than assuming a fixed order
- [x] Clustering is opt-in and leaves the previous single-pair output
      byte-identical when unset
- [x] Every mask class is rasterized in the imagery CRS
- [x] Derived training images, masks, predictions, and visualizer rasters
      select BigTIFF when their size may exceed the classic TIFF limit
- [ ] A dev retraining run confirms the above end-to-end *(outstanding — see
      [test-plan.md](test-plan.md))*

## HASTE Components Affected

| Component | Impact |
|---|---|
| `docker/` | `training/code/` — masks, training, inference, and their tests |
| `hastelib/src/hastegeo/core/` | `utils/label_classes.py` (new), `models/training.py` |
| `hastelib/src/hastegeo/processors/` | `train.py` derives `use_constraint_loss` |

## Deployment note

This feature spans **two independently deployed artifacts**:

| Change | Ships via | Artifact |
|---|---|---|
| `docker/training/code/**` | `docker-build-and-push.yml` | training image |
| `hastelib/**` | `deploy-apps.yml` | `hastegeo` wheel → Function Apps |

Deploying only one leaves the config generator and the code that reads it out
of step. See [rollout.md](rollout.md).

## Related Specs

| Spec | Relationship |
|---|---|
| [`../batch-compute-expansion/`](../batch-compute-expansion/) | multi-GPU training runs on those pools |
| [`../gdal-compensating-controls/`](../gdal-compensating-controls/) | `harden_gdal()` is preserved in the touched scripts |

## Document Index

| Document | Purpose | Status |
|---|---|---|
| [design.md](design.md) | Class layout contract, clustering, CRS constraints, config | in-review |
| [test-plan.md](test-plan.md) | Coverage matrix and the outstanding verification gaps | in-review |
| [rollout.md](rollout.md) | Two-artifact deploy, retraining requirement, rollback | in-review |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-20 | Keep HASTE-only hardening rather than taking upstream wholesale | Upstream lacks subprocess error reporting, adaptive patch sizing, `initial_weights_fn`, CPU fallback and `harden_gdal()`; a straight port would delete all of it |
| 2026-08-20 | Validate that "Damaged Building" is class value 3 rather than plumbing the index downstream | `merge_with_building_footprints.py` and the inference palette hardcode 3; that assumption predates this work and deserves its own change |
| 2026-08-21 | Enable the constraint loss automatically from the project's classes | It had no UI surface and was never set, so the weak label was being trained as a hard class on every run |
| 2026-08-21 | Give "No Damage" no output channel at all | Penalizing its probability only made it unattractive; removing the channel makes it unrepresentable |
| 2026-08-21 | Choose training precision at runtime | HASTE's Batch pools are heterogeneous — T4s have no bf16 — so `bf16-mixed` cannot be hardcoded as upstream does |
| 2026-08-21 | Keep `log_dict(train_metrics)` where upstream dropped it | `hastegeo`'s `tbparser` reads `train_MulticlassAccuracy` out of the TensorBoard events |
| 2026-08-26 | Use `BIGTIFF=IF_SAFER` for rasterio-generated training artifacts | `YES` changes every small output; `IF_SAFER` keeps classic TIFFs when safe and prevents the observed 4 GiB write failure |
