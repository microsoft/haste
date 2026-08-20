# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the config helpers in ``bda.config``."""

import os
import sys
import unittest

# The `bda` package lives next to this file and is not installed.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from bda.config import (  # noqa: E402
    _validate_config,
    _validate_optional_config,
    normalize_gpu_ids,
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


if __name__ == "__main__":
    unittest.main()
