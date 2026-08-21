# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the config helpers in ``bda.config``."""

import os
import sys
import unittest

# The `bda` package lives in the parent directory and is not installed.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from bda.config import (  # noqa: E402
    DAMAGED_CLASS_INDEX,
    _validate_config,
    _validate_optional_config,
    _validate_optional_values,
    find_class_value,
    normalize_class_name,
    normalize_gpu_ids,
    resolve_constraint_indices,
)


class TestNormalizeGpuIds(unittest.TestCase):
    def test_list(self):
        self.assertEqual(normalize_gpu_ids([0, 1, 2]), [0, 1, 2])

    def test_single_int(self):
        self.assertEqual(normalize_gpu_ids(2), [2])

    def test_single_gpu_id_fallback(self):
        self.assertEqual(normalize_gpu_ids(None, 3), [3])

    def test_gpu_ids_takes_precedence_over_gpu_id(self):
        self.assertEqual(normalize_gpu_ids([0, 1], 5), [0, 1])

    def test_comma_string(self):
        self.assertEqual(normalize_gpu_ids("0,1,2"), [0, 1, 2])

    def test_space_string(self):
        self.assertEqual(normalize_gpu_ids("0 1 2"), [0, 1, 2])

    def test_dedupe_preserves_order(self):
        self.assertEqual(normalize_gpu_ids([0, 0, 1, 1, 2]), [0, 1, 2])

    def test_none_is_empty(self):
        self.assertEqual(normalize_gpu_ids(None, None), [])

    def test_gpu_id_zero_is_not_treated_as_missing(self):
        """0 is a valid GPU id and must not be swallowed by a falsy check."""
        self.assertEqual(normalize_gpu_ids(None, 0), [0])


class TestResolveConstraintIndices(unittest.TestCase):
    """Only one of the two class indices is safe to derive.

    "No Damage" is read solely by the loss, so it varies freely. "Damaged
    Building" must stay at its pipeline value because
    merge_with_building_footprints.py and the inference palette both hardcode
    it.
    """

    STANDARD = ["Background", "Building", "Damaged Building", "No Damage"]

    def test_disabled_returns_no_index(self):
        no_damage, damaged = resolve_constraint_indices(
            ["Background", "Building"], use_constraint_loss=False
        )
        self.assertIsNone(no_damage)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_disabled_does_not_validate_classes(self):
        """A project not using the loss is unaffected by its requirements."""
        no_damage, _ = resolve_constraint_indices(
            ["Anything", "At", "All"], use_constraint_loss=False
        )
        self.assertIsNone(no_damage)

    def test_standard_layout(self):
        no_damage, damaged = resolve_constraint_indices(
            self.STANDARD, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 4)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_no_damage_index_is_derived_not_hardcoded(self):
        """A Cloud class after Damaged Building shifts No Damage to 5."""
        classes = [
            "Background",
            "Building",
            "Damaged Building",
            "Cloud",
            "No Damage",
        ]
        no_damage, damaged = resolve_constraint_indices(
            classes, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 5)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_damaged_class_off_by_position_is_rejected(self):
        """Training would disagree with merge/palette, so refuse to start."""
        classes = [
            "Background",
            "Cloud",
            "Building",
            "Damaged Building",
            "No Damage",
        ]
        with self.assertRaises(ValueError) as ctx:
            resolve_constraint_indices(classes, use_constraint_loss=True)
        message = str(ctx.exception)
        self.assertIn("Damaged Building", message)
        self.assertIn("merge_with_building_footprints.py", message)

    def test_missing_no_damage_is_rejected(self):
        classes = ["Background", "Building", "Damaged Building"]
        with self.assertRaises(ValueError) as ctx:
            resolve_constraint_indices(classes, use_constraint_loss=True)
        self.assertIn("No Damage", str(ctx.exception))

    def test_missing_damaged_building_is_rejected(self):
        classes = ["Background", "Building", "No Damage"]
        with self.assertRaises(ValueError) as ctx:
            resolve_constraint_indices(classes, use_constraint_loss=True)
        self.assertIn("Damaged Building", str(ctx.exception))

    def test_snake_case_names_are_matched(self):
        """The PutProject docstring's own example uses `no_damage`."""
        classes = ["background", "building", "damaged_building", "no_damage"]
        no_damage, damaged = resolve_constraint_indices(
            classes, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 4)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_casing_and_separators_are_ignored(self):
        classes = [
            "BACKGROUND",
            "building",
            "Damaged-Building",
            "nO   dAmAgE",
        ]
        no_damage, damaged = resolve_constraint_indices(
            classes, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 4)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_surrounding_whitespace_is_ignored(self):
        classes = ["Background", "Building", " Damaged Building ", "No Damage"]
        no_damage, damaged = resolve_constraint_indices(
            classes, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 4)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_ui_picker_order_is_supported(self):
        """The UI catalog order, minus the classes that follow No Damage.

        Cloud sits between Damaged Building and No Damage in
        ui/src/assets/json/settings.json, which is the layout the old
        hardcoded `y == 4` got wrong.
        """
        classes = [
            "Background",
            "Building",
            "Damaged Building",
            "Cloud",
            "No Damage",
        ]
        no_damage, damaged = resolve_constraint_indices(
            classes, use_constraint_loss=True
        )
        self.assertEqual(no_damage, 5)
        self.assertEqual(damaged, DAMAGED_CLASS_INDEX)

    def test_no_damage_must_be_the_final_class(self):
        """It has no output channel, so it has to be the last mask value.

        Note this rules out the UI catalog's full order, where Flood Extent
        follows No Damage.
        """
        classes = [
            "Background",
            "Building",
            "Damaged Building",
            "No Damage",
            "Flood Extent",
        ]
        with self.assertRaises(ValueError) as ctx:
            resolve_constraint_indices(classes, use_constraint_loss=True)
        message = str(ctx.exception)
        self.assertIn("LAST", message)
        self.assertIn("Flood Extent", message)

    def test_error_lists_the_configured_classes(self):
        """The message has to show what was actually there to be actionable."""
        classes = ["Background", "Building", "Destroyed"]
        with self.assertRaises(ValueError) as ctx:
            resolve_constraint_indices(classes, use_constraint_loss=True)
        self.assertIn("Destroyed", str(ctx.exception))


class TestNormalizeClassName(unittest.TestCase):
    def test_equivalent_spellings_collapse(self):
        forms = [
            "No Damage",
            "no damage",
            "NO DAMAGE",
            "no_damage",
            "No-Damage",
            "  no   damage  ",
        ]
        normalized = {normalize_class_name(f) for f in forms}
        self.assertEqual(normalized, {"no damage"})

    def test_distinct_names_stay_distinct(self):
        self.assertNotEqual(
            normalize_class_name("Damaged Building"),
            normalize_class_name("No Damage"),
        )

    def test_find_class_value_is_one_based(self):
        classes = ["Background", "Building", "Damaged Building"]
        self.assertEqual(find_class_value(classes, "Background"), 1)
        self.assertEqual(find_class_value(classes, "damaged_building"), 3)

    def test_find_class_value_returns_none_when_absent(self):
        self.assertIsNone(find_class_value(["Background"], "No Damage"))


class TestValidateOptionalConfig(unittest.TestCase):
    """The new opt-in keys must not become required for existing configs."""

    def _minimal_config(self):
        return {
            "experiment_name": "x",
            "experiment_dir": "/tmp/x",
            "imagery": {
                "raw_fn": "a.tif",
                "num_channels": 3,
                "normalization_means": [0, 0, 0],
                "normalization_stds": [255, 255, 255],
            },
            "labels": {
                "fn": "a.geojson",
                "classes": ["Background", "Building"],
                "buffer_in_meters": 3,
                "class_to_buffer": "Building",
                "class_to_buffer_by": "Background",
            },
            "training": {
                "learning_rate": 0.0001,
                "max_epochs": 1,
                "batch_size": 1,
                "gpu_id": 0,
                "log_dir": "logs/",
                "checkpoint_subdir": "checkpoints/",
                "use_constraint_loss": False,
                "initial_weights_fn": None,
            },
            "inference": {
                "output_subdir": "outputs/",
                "batch_size": 1,
                "gpu_id": 0,
                "checkpoint_fn": "last.ckpt",
            },
        }

    def test_config_without_new_keys_still_validates(self):
        config = self._minimal_config()
        _validate_config(config)
        _validate_optional_config(config)  # must not raise

    def test_new_keys_accepted_when_present(self):
        config = self._minimal_config()
        config["labels"]["cluster_size_in_meters"] = 1000.0
        config["labels"]["min_pixels_per_cluster"] = 500
        config["training"]["gpu_ids"] = [0, 1]
        _validate_optional_config(config)  # must not raise

    def test_new_keys_accept_null(self):
        """The generated YAML emits these as null when unset."""
        config = self._minimal_config()
        config["labels"]["cluster_size_in_meters"] = None
        config["labels"]["min_pixels_per_cluster"] = None
        config["training"]["gpu_ids"] = None
        _validate_optional_config(config)  # must not raise

    def test_wrong_type_is_rejected(self):
        config = self._minimal_config()
        config["labels"]["cluster_size_in_meters"] = "1000"
        with self.assertRaises(TypeError):
            _validate_optional_config(config)


class TestValidateOptionalValues(unittest.TestCase):
    """Type checks alone let nonsense reach the grid logic."""

    def _labels(self, **kwargs):
        return {"labels": dict(kwargs), "training": {}}

    def test_absent_keys_are_fine(self):
        _validate_optional_values({})  # must not raise

    def test_null_values_are_fine(self):
        _validate_optional_values(
            self._labels(
                cluster_size_in_meters=None, min_pixels_per_cluster=None
            )
        )

    def test_valid_values_pass(self):
        _validate_optional_values(
            self._labels(
                cluster_size_in_meters=1000.0, min_pixels_per_cluster=500
            )
        )

    def test_zero_cluster_size_is_rejected(self):
        """np.arange(step=0) raises ZeroDivisionError deep in the grid loop."""
        with self.assertRaises(ValueError) as ctx:
            _validate_optional_values(self._labels(cluster_size_in_meters=0))
        self.assertIn("cluster_size_in_meters", str(ctx.exception))

    def test_negative_cluster_size_is_rejected(self):
        """A negative step yields zero cells, i.e. silently no training data."""
        with self.assertRaises(ValueError):
            _validate_optional_values(
                self._labels(cluster_size_in_meters=-500.0)
            )

    def test_negative_min_pixels_is_rejected(self):
        """A negative minimum quietly disables culling."""
        with self.assertRaises(ValueError) as ctx:
            _validate_optional_values(self._labels(min_pixels_per_cluster=-1))
        self.assertIn("min_pixels_per_cluster", str(ctx.exception))

    def test_zero_min_pixels_is_allowed(self):
        """0 is meaningful: keep every cluster."""
        _validate_optional_values(self._labels(min_pixels_per_cluster=0))

    def test_negative_gpu_id_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            _validate_optional_values(
                {"labels": {}, "training": {"gpu_ids": [0, -1]}}
            )
        self.assertIn("gpu_ids", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
