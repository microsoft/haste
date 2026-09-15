# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Allowlisted command routing with native prediction COG conversion fixtures."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fiona
import numpy as np
import rasterio
import shapely.geometry
import yaml
from rasterio.transform import from_origin

CODE_DIR = str(Path(__file__).resolve().parents[1])
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import run_workflow as workflow  # noqa: E402


class WorkflowPredictionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "inference"
        self.output.mkdir()
        (self.root / "inputs").mkdir()
        self.config = {
            "experiment_dir": str(self.root),
            "inference": {
                "output_subdir": "inference",
                "predictions_gpkg_fileprefix": "buildings",
            },
        }
        self.config_fn = self.root / "experiment.yml"

    def write_prediction(self, name):
        path = self.output / name
        # Values 1 and 3 make accidental averaged categorical overviews visible.
        values = (np.indices((520, 520)).sum(axis=0) % 2 * 2 + 1).astype(
            np.uint8
        )
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=520,
            height=520,
            count=1,
            dtype="uint8",
            crs="EPSG:32610",
            transform=from_origin(500000, 4200000, 1, 1),
            nodata=0,
        ) as dst:
            dst.write(values, 1)
        return str(path)

    def run_workflow(self):
        self.config_fn.write_text(yaml.safe_dump(self.config))
        # Only existence is checked in this dispatcher test; no fake imagery I/O.
        footprints = self.root / "inputs" / "building_footprints.gpkg"
        with mock.patch.dict(
            os.environ, {"AZ_BATCH_TASK_WORKING_DIR": str(self.root)}
        ):
            with mock.patch.object(
                sys,
                "argv",
                [
                    "run_workflow.py",
                    "--config",
                    str(self.config_fn),
                    "--step",
                    "inference",
                ],
            ), mock.patch.object(workflow, "run_subprocess") as run:
                original_exists = os.path.exists
                with mock.patch.object(
                    os.path,
                    "exists",
                    side_effect=lambda path: str(path) == str(footprints)
                    or original_exists(path),
                ):
                    workflow.main()
        return run.call_args_list

    def test_default_legacy_command_unchanged_and_no_training(self):
        prediction = self.write_prediction("native_predictions.tif")
        calls = self.run_workflow()
        self.assertEqual(
            calls[0].args,
            (
                [
                    "python",
                    "inference.py",
                    "--config",
                    str(self.config_fn),
                    "--overwrite",
                ],
                "inference.py",
            ),
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[1].args[1], "merge_with_building_footprints.py")
        self.assertEqual(calls[2].args[1], "output2visualizer.py")
        self.assertNotIn("--preserve_source_identity", calls[1].args[0])
        self.assertIn(prediction, calls[1].args[0])
        with rasterio.open(prediction) as src:
            self.assertEqual(src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG")
            self.assertTrue(src.overviews(1))
            self.assertTrue(
                set(np.unique(src.read(1, out_shape=(260, 260)))) <= {1, 3}
            )

    def test_dino_dispatch_uses_explicit_filename_and_common_stages(self):
        self.write_prediction("stale_predictions.tif")
        selected = self.write_prediction("selected_predictions.tif")
        self.config["inference"].update(
            adapter="dinov3_upernet",
            predictions_filename="selected_predictions.tif",
            preserve_source_identity=True,
        )
        calls = self.run_workflow()
        self.assertEqual(calls[0].args[0][1], "inference_dinov3.py")
        self.assertEqual(calls[0].args[1], "inference_dinov3.py")
        self.assertEqual(
            [call.args[1] for call in calls],
            [
                "inference_dinov3.py",
                "merge_with_building_footprints.py",
                "output2visualizer.py",
                "gdal_translate",
            ],
        )
        self.assertIn("--preserve_source_identity", calls[1].args[0])
        self.assertIn(selected, calls[1].args[0])
        self.assertIn(selected, calls[2].args[0])
        self.assertIn("OVERVIEW_RESAMPLING=NEAREST", calls[3].args[0])
        self.assertIn("OVERVIEWS=IGNORE_EXISTING", calls[3].args[0])

    def test_unknown_adapter_rejected_before_any_subprocess(self):
        self.config["inference"]["adapter"] = "unapproved.module"
        with mock.patch.object(workflow, "run_subprocess") as run:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                self.run_workflow()
            run.assert_not_called()

    def test_prediction_selection_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            workflow.prediction_path(self.config, str(self.output))
        self.write_prediction("one_predictions.tif")
        self.write_prediction("two_predictions.tif")
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            workflow.prediction_path(self.config, str(self.output))
        self.config["inference"]["adapter"] = "dinov3_upernet"
        with self.assertRaisesRegex(ValueError, "requires"):
            workflow.prediction_path(self.config, str(self.output))
        for name in [
            "../one_predictions.tif",
            "/tmp/one_predictions.tif",
            "no_suffix.tif",
        ]:
            self.config["inference"]["predictions_filename"] = name
            with self.assertRaises(ValueError):
                workflow.prediction_path(self.config, str(self.output))
        self.config["inference"][
            "predictions_filename"
        ] = "missing_predictions.tif"
        with self.assertRaises(FileNotFoundError):
            workflow.prediction_path(self.config, str(self.output))

    def test_native_shared_workflow_with_only_classifier_faked(self):
        import inference_dinov3 as inference
        from test_inference_dinov3 import FakeClassifier, write_rgb

        gdal_translate = shutil.which(
            "gdal_translate", path=str(Path(sys.executable).resolve().parent)
        ) or shutil.which("gdal_translate")
        if gdal_translate is None:
            self.skipTest("Native gdal_translate is required")
        rgb_fn = self.root / "inputs" / "post_rgb.tif"
        write_rgb(rgb_fn, 5, 9)
        with fiona.open(
            self.root / "inputs" / "building_footprints.gpkg",
            "w",
            driver="GPKG",
            crs="EPSG:32610",
            schema={
                "geometry": "Polygon",
                "properties": {"id": "int", "overture_id": "str"},
            },
        ) as dst:
            for identifier, x in [(17, 500000), (91, 501000)]:
                dst.write(
                    {
                        "geometry": shapely.geometry.mapping(
                            shapely.geometry.box(x, 4199990, x + 18, 4200000)
                        ),
                        "properties": {
                            "id": identifier,
                            "overture_id": f"overture-{identifier}",
                        },
                    }
                )
        self.config["imagery"] = {
            "rgb_fn": str(rgb_fn),
            "raw_fn": "must-not-be-used.tif",
        }
        self.config["inference"].update(
            adapter="dinov3_upernet",
            predictions_filename="selected_predictions.tif",
            preserve_source_identity=True,
            checkpoint_fn="fake.ckpt",
            backbone_config_fn="fake.json",
            checkpoint_sha256="a" * 64,
            backbone_config_sha256="b" * 64,
            patch_size=32,
            padding=8,
            batch_size=2,
            num_workers=2,
        )
        self.config_fn.write_text(yaml.safe_dump(self.config))
        stages = []

        def execute(command, stage):
            stages.append(stage)
            if stage == "inference_dinov3.py":
                with mock.patch.object(
                    inference, "load_model", return_value=FakeClassifier()
                ), mock.patch.object(
                    sys, "argv", command[1:] + ["--device", "cpu"]
                ):
                    inference.main()
                return
            if command[0] == "python":
                command = [sys.executable, *command[1:]]
            else:
                command = [gdal_translate, *command[1:]]
            result = subprocess.run(
                command,
                cwd=CODE_DIR,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr
            )

        with mock.patch.dict(
            os.environ, {"AZ_BATCH_TASK_WORKING_DIR": str(self.root)}
        ):
            with mock.patch.object(
                sys,
                "argv",
                [
                    "run_workflow.py",
                    "--config",
                    str(self.config_fn),
                    "--step",
                    "inference",
                ],
            ), mock.patch.object(
                workflow, "run_subprocess", side_effect=execute
            ):
                workflow.main()
        self.assertEqual(
            stages,
            [
                "inference_dinov3.py",
                "merge_with_building_footprints.py",
                "output2visualizer.py",
                "gdal_translate",
            ],
        )
        with fiona.open(self.output / "buildings.gpkg") as src:
            rows = [dict(r["properties"]) for r in src]
        self.assertEqual([r["id"] for r in rows], [0, 1])
        self.assertEqual([r["source_building_id"] for r in rows], ["17", "91"])
        self.assertIsNone(rows[1]["damage_pct_0m"])
        self.assertEqual(rows[1]["unknown_pct"], 1)
        for name in ["selected_predictions.tif", "selected_visualizer.tif"]:
            with rasterio.open(self.output / name) as src:
                self.assertEqual(
                    src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
                )
                self.assertEqual(src.crs.to_epsg(), 32610)
                self.assertEqual(src.shape, (5, 9))
        self.assertTrue(
            (self.root / "logs" / "workflow_progress.log").is_file()
        )


if __name__ == "__main__":
    unittest.main()
