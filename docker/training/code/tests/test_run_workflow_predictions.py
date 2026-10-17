# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Existing CLI branches use real GIS producers; only process launch is faked."""

import importlib
import json
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
import pytest
import rasterio.shutil
import shapely.geometry
import yaml
from rasterio.transform import from_origin
from shapely.geometry import box

from hastelib.tests.core.prediction_fixtures import write_gpkg, write_raster

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))
import merge_with_building_footprints as merge  # noqa: E402
import output2visualizer as visualizer  # noqa: E402
import run_workflow as workflow  # noqa: E402


@pytest.fixture
def workflow_case(tmp_path, mocker):
    (tmp_path / "inputs").mkdir()
    output = tmp_path / "inference"
    output.mkdir()
    fp = write_gpkg(
        tmp_path / "inputs/building_footprints.gpkg",
        [{"id": "building-0"}],
        fields={"id": "str"},
        crs="EPSG:32610",
        geometries=[box(500020, 4170020, 500040, 4170040)],
    )
    config = {
        "experiment_dir": str(tmp_path),
        "labels": {"fn": fp},
        "training": {"checkpoint_subdir": "checkpoints"},
        "inference": {
            "output_subdir": "inference",
            "predictions_gpkg_fileprefix": "predicted_damage_model",
            "prediction_attrs_filename": "prediction_attrs_1234.json",
            "prediction_revision": "run-1234",
        },
    }
    attrs = output / "prediction_attrs_1234.json"
    steps = []

    def launch(command, step):
        steps.append(step)
        if step == "create_masks.py":
            return
        if step == "fine_tune.py":
            (tmp_path / "checkpoints").mkdir()
            (tmp_path / "checkpoints/last.ckpt").touch()
        elif step == "inference.py":
            write_raster(
                output / "image_predictions.tif",
                np.full((10, 10), 3, dtype="uint8"),
                from_origin(500000, 4170100, 10, 10),
            )
        elif step == "merge_with_building_footprints.py":
            assert not attrs.exists()
            merge.main(merge.set_up_parser().parse_args(command[2:]))
        elif step == "output2visualizer.py":
            # Attributes must exist before visualization, not on results GET.
            payload = json.loads(attrs.read_text())
            assert payload["predictionRevision"] == "run-1234"
            assert payload["classes"] == ["Damaged"]
            visualizer.main(visualizer.set_up_parser().parse_args(command[2:]))
        elif step == "gdal_translate":
            rasterio.shutil.copy(command[-2], command[-1], driver="COG")
        else:
            pytest.fail(f"Unexpected step: {step}")

    mocker.patch.dict(
        os.environ,
        {
            "AZ_BATCH_TASK_WORKING_DIR": str(tmp_path),
            "GDAL_TRANSLATE_PARAMS": "",
        },
    )
    mocker.patch.object(workflow, "run_subprocess", side_effect=launch)

    def run(step="inference"):
        config_path = tmp_path / "config.yml"
        config_path.write_text(yaml.safe_dump(config))
        argv = ["run_workflow.py", "--config", str(config_path)]
        if step is not None:
            argv += ["--step", step]
        mocker.patch.object(sys, "argv", argv)
        workflow.main()

    return config, run, steps, attrs


@pytest.mark.parametrize("step", ["inference", None])
def test_inference_and_default_all_write_eager_sidecars(workflow_case, step):
    config, run, steps, attrs = workflow_case
    run(step)
    expected = [
        "inference.py",
        "merge_with_building_footprints.py",
        "output2visualizer.py",
        "gdal_translate",
    ]
    assert (
        steps
        == (["create_masks.py", "fine_tune.py"] if step is None else [])
        + expected
    )
    payload = json.loads(attrs.read_text())
    assert payload["schemaVersion"] == 1
    assert payload["flavor"] == "inference"
    assert payload["ids"] == [0]
    assert payload["overtureIds"] == ["building-0"]
    with fiona.open(attrs.parent / "predicted_damage_model.gpkg") as src:
        assert next(iter(src))["properties"]["id"] == 0


@pytest.mark.parametrize("step", ["inference", None])
@pytest.mark.parametrize(
    "field", ["prediction_attrs_filename", "prediction_revision"]
)
def test_missing_required_settings_fail_before_work(
    workflow_case, step, field
):
    config, run, steps, attrs = workflow_case
    del config["inference"][field]
    with pytest.raises(ValueError, match=field):
        run(step)
    assert steps == [] and not attrs.exists()


def test_training_only_is_exempt(workflow_case, mocker):
    config, run, steps, attrs = workflow_case
    del config["inference"]["prediction_attrs_filename"]
    del config["inference"]["prediction_revision"]
    check = mocker.spy(workflow, "prediction_attrs_settings")
    run("training")
    check.assert_not_called()
    assert steps == ["create_masks.py", "fine_tune.py"]
    assert not attrs.exists()


@pytest.mark.parametrize("adapter", ["dinov2_upernet", "dinov3_upernet"])
@pytest.mark.parametrize("step", ["training", None])
def test_transformer_adapters_reject_training_before_work(
    workflow_case, adapter: str, step: str | None
) -> None:
    config, run, steps, attrs = workflow_case
    config["inference"]["adapter"] = adapter
    with pytest.raises(ValueError, match="inference-only"):
        run(step)
    assert steps == [] and not attrs.exists()


def test_missing_footprints_fails_without_sidecar(workflow_case):
    config, run, steps, attrs = workflow_case
    fiona.remove(config["labels"]["fn"], driver="GPKG")
    with pytest.raises(RuntimeError, match="footprints missing"):
        run()
    assert not attrs.exists()


def test_sidecar_failure_stops_existing_workflow(workflow_case, mocker):
    config, run, steps, attrs = workflow_case
    mocker.patch(
        "hastegeo.core.utils.prediction_attrs.write_prediction_attrs",
        side_effect=OSError("disk full"),
    )
    with pytest.raises(OSError):
        run()
    assert steps == ["inference.py", "merge_with_building_footprints.py"]
    assert not attrs.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        *[
            ("prediction_attrs_filename", value)
            for value in (
                "../outside.json",
                "/outside.json",
                "dir/file.json",
                "dir\\file.json",
                "name.gpkg",
                ".json",
                "",
                None,
            )
        ],
        *[("prediction_revision", value) for value in ("", "  ", None, 12)],
    ],
)
def test_unsafe_filename_or_missing_revision_is_rejected(field, value):
    settings = {
        "prediction_attrs_filename": "attrs.json",
        "prediction_revision": "run-1",
    }
    settings[field] = value
    with pytest.raises(ValueError):
        workflow.prediction_attrs_settings({"inference": settings})


def test_shipped_template_requires_a_fresh_revision():
    template = yaml.safe_load((CODE_DIR / "configs/config.yml").read_text())
    assert (
        template["inference"]["prediction_attrs_filename"]
        == "prediction_attrs.json"
    )
    assert template["inference"]["prediction_revision"] == ""
    with pytest.raises(ValueError, match="prediction_revision"):
        workflow.prediction_attrs_settings(template)


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
                "prediction_attrs_filename": "attrs.json",
                "prediction_revision": "catalog-fixture",
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
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_workflow.py",
                        "--config",
                        str(self.config_fn),
                        "--step",
                        "inference",
                    ],
                ),
                mock.patch.object(workflow, "run_subprocess") as run,
                mock.patch(
                    "hastegeo.core.utils.prediction_attrs.write_prediction_attrs"
                ),
            ):
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

    def test_dino_dispatch_uses_explicit_filename_and_common_stages(
        self,
    ) -> None:
        self.write_prediction("stale_predictions.tif")
        selected = self.write_prediction("selected_predictions.tif")
        for adapter, entrypoint in (
            ("dinov2_upernet", "inference_dinov2.py"),
            ("dinov3_upernet", "inference_dinov3.py"),
        ):
            with self.subTest(adapter=adapter):
                self.config["inference"].update(
                    adapter=adapter,
                    predictions_filename="selected_predictions.tif",
                    preserve_source_identity=True,
                )
                calls = self.run_workflow()
                self.assertEqual(calls[0].args[0][1], entrypoint)
                self.assertEqual(calls[0].args[1], entrypoint)
                self.assertEqual(
                    [call.args[1] for call in calls],
                    [
                        entrypoint,
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

    def test_prediction_selection_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            workflow.prediction_path(self.config, str(self.output))
        self.write_prediction("one_predictions.tif")
        self.write_prediction("two_predictions.tif")
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            workflow.prediction_path(self.config, str(self.output))
        for adapter in ("dinov2_upernet", "dinov3_upernet"):
            self.config["inference"]["adapter"] = adapter
            self.config["inference"].pop("predictions_filename", None)
            with (
                self.subTest(adapter=adapter),
                self.assertRaisesRegex(ValueError, "requires"),
            ):
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

    def test_native_shared_workflow_with_only_classifier_faked(self) -> None:
        self.assert_native_catalog_workflow(
            "dinov3_upernet", "inference_dinov3.py"
        )

    def test_native_dinov2_workflow_with_only_classifier_faked(self) -> None:
        self.assert_native_catalog_workflow(
            "dinov2_upernet", "inference_dinov2.py"
        )

    def assert_native_catalog_workflow(
        self, adapter: str, entrypoint: str
    ) -> None:
        from tests.test_inference_dinov3 import FakeClassifier, write_rgb

        inference = importlib.import_module(entrypoint.removesuffix(".py"))

        gdal_translate = shutil.which(
            "gdal_translate", path=str(Path(sys.executable).resolve().parent)
        ) or shutil.which("gdal_translate")
        if gdal_translate is None:
            self.skipTest("Native gdal_translate is required")
        rgb_fn = self.root / "inputs" / "post_rgb.tif"
        mask = np.full((5, 9), 255, dtype=np.uint8)
        mask[1:3, 2:4] = 0
        rgb = write_rgb(rgb_fn, 5, 9, mask=mask)
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
            for identifier, bounds in [
                (17, (500000, 4199990, 500004, 4200000)),
                (91, (501000, 4199990, 501004, 4200000)),
                (42, (500004, 4199994, 500008, 4199998)),
            ]:
                dst.write(
                    {
                        "geometry": shapely.geometry.mapping(
                            shapely.geometry.box(*bounds)
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
            adapter=adapter,
            predictions_filename="selected_predictions.tif",
            preserve_source_identity=True,
            checkpoint_fn="fake.ckpt",
            checkpoint_sha256="a" * 64,
            patch_size=32,
            padding=8,
            batch_size=2,
            num_workers=2,
        )
        if adapter == "dinov3_upernet":
            self.config["inference"].update(
                backbone_config_fn="fake.json",
                backbone_config_sha256="b" * 64,
            )
        self.config_fn.write_text(yaml.safe_dump(self.config))
        stages = []
        attrs = self.output / "attrs.json"

        def execute(command: list[str], stage: str) -> None:
            stages.append(stage)
            if stage == entrypoint:
                self.assertFalse(attrs.exists())
                with (
                    mock.patch.object(
                        inference, "load_model", return_value=FakeClassifier()
                    ),
                    mock.patch.object(
                        sys, "argv", command[1:] + ["--device", "cpu"]
                    ),
                ):
                    inference.main()
                return
            if stage == "merge_with_building_footprints.py":
                self.assertFalse(attrs.exists())
            elif stage == "output2visualizer.py":
                payload = json.loads(attrs.read_text())
                self.assertEqual(
                    payload["predictionRevision"], "catalog-fixture"
                )
                self.assertEqual(
                    payload["classes"], ["Damaged", "Unknown", "Unknown"]
                )
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
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_workflow.py",
                        "--config",
                        str(self.config_fn),
                        "--step",
                        "inference",
                    ],
                ),
                mock.patch.object(
                    workflow, "run_subprocess", side_effect=execute
                ),
            ):
                workflow.main()
        self.assertEqual(
            stages,
            [
                entrypoint,
                "merge_with_building_footprints.py",
                "output2visualizer.py",
                "gdal_translate",
            ],
        )
        with fiona.open(self.output / "buildings.gpkg") as src:
            rows = [dict(r["properties"]) for r in src]
        self.assertEqual([r["id"] for r in rows], [0, 1, 2])
        self.assertEqual(
            [r["source_building_id"] for r in rows], ["17", "91", "42"]
        )
        self.assertEqual([r["overture_id"] for r in rows], ["17", "91", "42"])
        self.assertAlmostEqual(rows[0]["damage_pct_0m"], 0.3)
        for row in rows[1:]:
            for suffix in ("0m", "10m", "20m"):
                self.assertIsNone(row[f"damage_pct_{suffix}"])
            self.assertEqual(row["unknown_pct"], 1)
            self.assertEqual(row["damaged"], 0)
        payload = json.loads(attrs.read_text())
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["flavor"], "inference")
        self.assertEqual(payload["n"], 3)
        self.assertEqual(payload["ids"], [0, 1, 2])
        self.assertEqual(payload["overtureIds"], ["17", "91", "42"])
        self.assertEqual(payload["damage"], [0.3, None, None])
        self.assertEqual(payload["unknown"], [0, 1, 1])
        self.assertEqual(payload["damaged"], [1, 0, 0])
        with rasterio.open(self.output / "selected_predictions.tif") as src:
            np.testing.assert_array_equal(
                src.read(1), np.where(mask, rgb[0] % 3 + 1, 0)
            )
            np.testing.assert_array_equal(src.read_masks(1), mask)
        with rasterio.open(self.output / "selected_visualizer.tif") as src:
            self.assertFalse(src.read(4)[1:3, 2:4].any())
            self.assertTrue((src.read(4)[:, :2] == 255).all())
            self.assertIsNone(src.nodata)
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
