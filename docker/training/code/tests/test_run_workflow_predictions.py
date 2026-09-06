# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Inference orchestration tests: real GDAL producers, no GPU or services."""

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fiona
import numpy as np
import rasterio
import rasterio.shutil
import yaml
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import merge_with_building_footprints as merge  # noqa: E402
import output2visualizer as visualizer  # noqa: E402
import run_workflow as workflow  # noqa: E402


class WorkflowPredictionsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        os.makedirs(os.path.join(self.directory, "inputs"))
        self.inference_dir = os.path.join(self.directory, "inference")
        os.makedirs(self.inference_dir)
        self.config_path = os.path.join(self.directory, "config.yaml")
        self.config = {
            "experiment_dir": self.directory,
            "inference": {
                "output_subdir": "inference",
                "predictions_gpkg_fileprefix": "predicted_damage_model",
                "prediction_attrs_filename": "prediction_attrs_1234.json",
                "prediction_revision": "run-1234",
            },
        }
        self.footprints = os.path.join(
            self.directory, "inputs", "building_footprints.gpkg"
        )
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:32610",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
        ) as dst:
            dst.write(
                {
                    "geometry": mapping(box(500020, 4170020, 500040, 4170040)),
                    "properties": {"id": "source-building"},
                }
            )
        self.attrs = os.path.join(
            self.inference_dir, "prediction_attrs_1234.json"
        )
        self.config["labels"] = {"fn": self.footprints}
        self.config["training"] = {"checkpoint_subdir": "checkpoints"}
        self.steps = []

    def run_step(self, command: list, step: str) -> None:
        """Replace only process launching; exercise the vector producers."""
        self.steps.append(step)
        if step == "create_masks.py":
            return
        elif step == "fine_tune.py":
            # Training is not under test; satisfy its checkpoint-output
            # contract without launching a GPU job or loading a model.
            checkpoint_dir = Path(self.directory, "checkpoints")
            checkpoint_dir.mkdir()
            (checkpoint_dir / "last.ckpt").touch()
        elif step == "inference.py":
            with rasterio.open(
                os.path.join(self.inference_dir, "image_predictions.tif"),
                "w",
                driver="COG",
                crs="EPSG:32610",
                width=10,
                height=10,
                count=1,
                dtype="uint8",
                nodata=0,
                transform=from_origin(500000, 4170100, 10, 10),
            ) as dst:
                dst.write(np.full((10, 10), 3, dtype="uint8"), 1)
        elif step == "merge_with_building_footprints.py":
            self.assertFalse(os.path.exists(self.attrs))
            merge.main(
                argparse.Namespace(
                    footprints_fn=command[
                        command.index("--footprints_fn") + 1
                    ],
                    predictions_fn=command[
                        command.index("--predictions_fn") + 1
                    ],
                    output_fn=command[command.index("--output_fn") + 1],
                    overwrite=True,
                )
            )
        elif step == "output2visualizer.py":
            # The sidecar must already exist BEFORE visualization begins.
            with open(self.attrs, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["predictionRevision"], "run-1234")
            self.assertEqual(payload["classes"], ["Damaged"])
            visualizer.main(
                argparse.Namespace(
                    merged_footprints_fn=command[
                        command.index("--merged_footprints_fn") + 1
                    ],
                    predictions_fn=command[
                        command.index("--predictions_fn") + 1
                    ],
                    output_fn=command[command.index("--output_fn") + 1],
                    overwrite=True,
                )
            )
        elif step == "gdal_translate":
            rasterio.shutil.copy(command[-2], command[-1], driver="COG")
        else:
            self.fail(f"Unexpected workflow step: {step}")

    def run_workflow(self, step: str | None = "inference") -> None:
        with open(self.config_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config, handle)
        argv = ["run_workflow.py", "--config", self.config_path]
        if step is not None:
            argv.extend(["--step", step])
        with patch.object(
            sys,
            "argv",
            argv,
        ), patch.dict(
            os.environ,
            {
                "AZ_BATCH_TASK_WORKING_DIR": self.directory,
                "GDAL_TRANSLATE_PARAMS": "",
            },
        ), patch.object(workflow, "run_subprocess", side_effect=self.run_step):
            workflow.main()

    def test_sidecar_is_eager_and_beside_gpkg_in_upload_directory(
        self,
    ) -> None:
        self.run_workflow()
        self.assertEqual(
            self.steps,
            [
                "inference.py",
                "merge_with_building_footprints.py",
                "output2visualizer.py",
                "gdal_translate",
            ],
        )
        with open(self.attrs, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["flavor"], "inference")
        self.assertEqual(payload["ids"], [0])
        self.assertEqual(payload["overtureIds"], ["source-building"])
        with fiona.open(
            os.path.join(self.inference_dir, "predicted_damage_model.gpkg")
        ) as src:
            self.assertEqual(next(iter(src))["properties"]["id"], 0)

    def test_default_all_writes_sidecar_after_training_and_merge(self) -> None:
        self.run_workflow(step=None)
        self.assertEqual(
            self.steps,
            [
                "create_masks.py",
                "fine_tune.py",
                "inference.py",
                "merge_with_building_footprints.py",
                "output2visualizer.py",
                "gdal_translate",
            ],
        )
        with open(self.attrs, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["predictionRevision"], "run-1234")
        self.assertEqual(payload["classes"], ["Damaged"])

    def test_each_missing_setting_fails_before_inference_or_default_all(
        self,
    ) -> None:
        for step in ("inference", None):
            for field in (
                "prediction_attrs_filename",
                "prediction_revision",
            ):
                original = self.config["inference"].pop(field)
                try:
                    with self.subTest(
                        step=step, field=field
                    ), self.assertRaisesRegex(ValueError, field):
                        self.run_workflow(step=step)
                    self.assertEqual(self.steps, [])
                    self.assertFalse(os.path.exists(self.attrs))
                finally:
                    self.config["inference"][field] = original

    def test_training_only_does_not_require_prediction_settings(self) -> None:
        del self.config["inference"]["prediction_attrs_filename"]
        del self.config["inference"]["prediction_revision"]
        with patch.object(
            workflow,
            "prediction_attrs_settings",
            side_effect=AssertionError("training must not validate sidecars"),
        ):
            self.run_workflow(step="training")
        self.assertEqual(self.steps, ["create_masks.py", "fine_tune.py"])
        self.assertFalse(os.path.exists(self.attrs))

    def test_shipped_template_requires_a_fresh_revision(self) -> None:
        with open(
            os.path.join(CODE_DIR, "configs", "config.yml"),
            encoding="utf-8",
        ) as handle:
            template = yaml.safe_load(handle)
        self.assertEqual(
            template["inference"]["prediction_attrs_filename"],
            "prediction_attrs.json",
        )
        self.assertEqual(template["inference"]["prediction_revision"], "")
        with self.assertRaisesRegex(ValueError, "prediction_revision"):
            workflow.prediction_attrs_settings(template)

    def test_missing_footprints_fails_without_sidecar(self) -> None:
        fiona.remove(self.footprints, driver="GPKG")
        with self.assertRaisesRegex(RuntimeError, "footprints missing"):
            self.run_workflow()
        self.assertFalse(os.path.exists(self.attrs))

    def test_sidecar_write_failure_fails_existing_workflow(self) -> None:
        with patch(
            "hastegeo.core.utils.prediction_attrs.write_prediction_attrs",
            side_effect=OSError("sidecar disk failure"),
        ), self.assertRaises(OSError):
            self.run_workflow()
        self.assertEqual(
            self.steps, ["inference.py", "merge_with_building_footprints.py"]
        )
        self.assertFalse(os.path.exists(self.attrs))

    def test_safe_filename_and_nonempty_revision_are_required(self) -> None:
        for filename in (
            "../outside.json",
            "/outside.json",
            "dir/file.json",
            "dir\\file.json",
            "name.gpkg",
            ".json",
            "",
            None,
        ):
            with self.subTest(filename=filename):
                self.config["inference"][
                    "prediction_attrs_filename"
                ] = filename
                with self.assertRaises(ValueError):
                    workflow.prediction_attrs_settings(self.config)
        self.config["inference"]["prediction_attrs_filename"] = "attrs.json"
        for revision in ("", "  ", None, 12):
            with self.subTest(revision=revision):
                self.config["inference"]["prediction_revision"] = revision
                with self.assertRaises(ValueError):
                    workflow.prediction_attrs_settings(self.config)
