# Test plan — Polygon training workflow sync

## Coverage

**92 container-side tests, plus 16 `hastegeo` tests.** Container-side tests
live in `docker/training/code/tests/` and run without the conda env unless
noted; `hastegeo` tests follow the repo's usual layout.

```bash
cd docker/training/code && python -m unittest discover -s tests -t .
PYTHONPATH=$PWD/hastelib/src python -m unittest \
    hastelib.tests.core.utils.test_label_classes -v
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_config.py` | 38 | GPU id normalization, constraint-index resolution, lenient class-name matching, optional-key type and range validation |
| `tests/test_trainers.py` | 17 | Channel layout, CE target shifting, constraint term, metric/inference agreement, gradient isolation, NaN guards |
| `tests/test_create_masks.py` | 13 | Grid assignment, STRtree/brute-force equivalence, CRS gate, extent clipping, skip-path exception type |
| `tests/test_datasets.py` | 10 | Channel clipping, too-few-bands rejection, preload equivalence and aliasing |
| `tests/test_create_masks_cleanup.py` | 9 | Stale and partial output removal, prefix safety |
| `tests/test_create_masks_writes.py` | 5 | BigTIFF option, profile immutability, both write forms, and production call-site wiring |
| `hastelib/tests/core/utils/test_label_classes.py` | 16 | The auto-enable decision across class layouts and spellings |

## Load-bearing tests

These are the ones that would catch a regression of the specific defects, and
each was **verified to fail against the code it replaced**:

| Test | Pins |
|---|---|
| `test_matches_reference_for_5_class_layout` | A `Cloud` class shifts `No Damage` to 5; the old hardcoded `y == 4` got this wrong |
| `test_no_damage_can_never_be_predicted` | The dev report. Fits logits and asserts the class is unrepresentable |
| `test_metric_predictions_match_what_inference_emits` | Reported accuracy measures the deployed prediction, not a channel-0 win |
| `test_unlabeled_channel_receives_no_gradient` | Channel 0 is emitted but never supervised |
| `test_matches_a_brute_force_scan` | The STRtree selects exactly what the scan it replaced did |
| `test_patches_are_identical_to_the_disk_path` | Preload is a speed-up; any difference in what it returns is a bug |
| `test_is_distinct_from_valueerror` | The cluster skip path cannot swallow a config error |
| `test_applies_if_safer_without_mutating_input_profile` | Both derived raster paths can exceed 4 GiB, and the source profile remains reusable |

## Method notes

Several behaviors are properties of an *objective* rather than of a function
return, so they are tested by optimizing raw logits directly against the loss —
no network in the way, so whatever the objective rewards is what it converges
to. That is how the under-constrained form was diagnosed: it left the
non-damaged channels at a dead-even 0.2000 split.

Cross-implementation agreement between `should_use_constraint_loss` (submit
side) and `resolve_constraint_indices` (container) was checked across nine class
layouts. They agree on all of them, so the submit side cannot enable the loss
for a config the container rejects.

## Outstanding verification

- [ ] **No end-to-end training run.** Clustering, DDP, preload, bf16 and the
      channel layout have not been exercised against real imagery or a real
      GPU. This is the gap that matters most — a dev retrain is the real test.
- [ ] **`tests/test_trainers.py` on real dependencies.** Run locally with
      `kornia` / `torchgeo` / `lightning` stubbed, since they are absent
      outside the training image. The loss itself depends only on `torch`,
      which is real, but confirm a clean run inside the image.
- [ ] **`tests/test_merge_with_building_footprints.py`** (pre-existing) cannot
      be collected without `fiona`/`geopandas`.
- [ ] **Whether HASTE masks were ever affected by the rasterize CRS bug.** Did
      not reproduce on GDAL 3.4.1. Decisive check: pull an existing
      experiment's `masks/` artifact and look for any value above 1. If it is
      all `{0, 1}`, every multi-class model trained here saw background only.
- [ ] **Affected-layer retraining with a BigTIFF image.** Unit tests pin the
      GDAL creation option without allocating a 4+ GiB array. Re-run the
      Buenaventura layer after deploying the patched training image to verify
      the production-sized path.

## CI gap

`docker/training/code/` is **not covered by CI** — no workflow runs these
tests, and `test_merge_with_building_footprints.py` had the same problem before
this work. Wiring `docker/training/code/tests/` into a workflow is a follow-up.
