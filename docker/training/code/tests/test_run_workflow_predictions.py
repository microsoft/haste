# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Existing CLI branches use real GIS producers; only process launch is faked."""

import json
import os
import sys
from pathlib import Path

import fiona
import numpy as np
import pytest
import rasterio.shutil
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
