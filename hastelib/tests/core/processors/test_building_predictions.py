# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""The interactive producer writes complete source-aligned native artifacts."""

import json

import fiona
import pytest
from hastegeo.core.processors.building_predictions import (
    write_building_predictions,
)
from hastegeo.core.utils.prediction_attrs import (
    FootprintPredictionMismatchError,
)
from shapely.geometry import box, shape

from ..prediction_fixtures import write_gpkg


@pytest.fixture
def footprints(tmp_path):
    return write_gpkg(
        tmp_path / "footprints.gpkg",
        [{"id": "building-0"}, {"id": "building-1"}],
        fields={"id": "str"},
    )


def write(tmp_path, footprints, rows, revision="run-1"):
    return write_building_predictions(
        footprints,
        rows,
        str(tmp_path / f"{revision}.gpkg"),
        str(tmp_path / f"{revision}.json"),
        prediction_revision=revision,
    )


def test_shuffled_replacement_preserves_geometry_crs_area_and_json(
    tmp_path, footprints
):
    result = write(
        tmp_path,
        footprints,
        [
            {"id": 1, "damaged": 1, "overtureId": "building-1"},
            {"id": 0, "damaged": 0},
        ],
    )
    assert result.count == result.payload["n"] == 2
    assert result.payload["flavor"] == "embedding"
    assert json.loads((tmp_path / "run-1.json").read_text()) == result.payload
    with fiona.open(result.gpkg_path, layer="predictions") as src:
        assert src.crs.to_epsg() == 6933
        for index, row in enumerate(src):
            assert row["properties"]["id"] == index
            assert row["properties"]["overture_id"] == f"building-{index}"
            assert row["properties"]["damaged"] == index
            assert row["properties"]["area"] == pytest.approx(100)
            assert shape(row["geometry"]).equals(
                box(index * 20, 0, index * 20 + 10, 10)
            )


@pytest.mark.parametrize(
    "rows,classes",
    [
        (
            [{"id": 0, "damaged": 0}, {"id": 1, "damaged": 0}],
            ["NotDamaged"] * 2,
        ),
        (
            [{"id": 0, "damaged": 1, "unknown": 0.2}, {"id": 1, "damaged": 0}],
            ["Unknown", "NotDamaged"],
        ),
    ],
)
def test_clear_is_distinct_from_undamaged_and_unknown(
    tmp_path, footprints, rows, classes
):
    result = write(tmp_path, footprints, rows)
    assert result.count == 2
    assert result.payload["classes"] == classes


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"id": 0, "damaged": 1}],
        [{"id": 0, "damaged": 1}, {"id": 0, "damaged": 0}],
        *[
            [{"id": value, "damaged": 0}, {"id": 1, "damaged": 0}]
            for value in (-1, 2, "0", 0.0, False)
        ],
        [None, {"id": 1, "damaged": 0}],
    ],
)
def test_invalid_identity_or_partial_coverage_writes_nothing(
    tmp_path, footprints, rows
):
    with pytest.raises(ValueError):
        write(tmp_path, footprints, rows)
    assert not (tmp_path / "run-1.gpkg").exists()
    assert not (tmp_path / "run-1.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        *[("damaged", value) for value in (None, 2, True, 1.5, "1")],
        *[
            ("unknown", value)
            for value in (
                None,
                True,
                "0.5",
                -0.1,
                1.1,
                float("nan"),
                float("inf"),
            )
        ],
    ],
)
def test_bad_prediction_values_are_rejected_before_writing(
    tmp_path, footprints, field, value
):
    rows = [{"id": 0, "damaged": 0}, {"id": 1, "damaged": 0}]
    rows[0][field] = value
    with pytest.raises(ValueError):
        write(tmp_path, footprints, rows)
    assert not (tmp_path / "run-1.gpkg").exists()


def test_explicit_overture_mismatch_and_input_alias_fail(tmp_path, footprints):
    with pytest.raises(FootprintPredictionMismatchError):
        write(
            tmp_path,
            footprints,
            [
                {"id": 0, "damaged": 0, "overtureId": "building-1"},
                {"id": 1, "damaged": 0},
            ],
        )
    with pytest.raises(ValueError):
        write_building_predictions(
            footprints,
            [],
            footprints,
            str(tmp_path / "a.json"),
            prediction_revision="run-1",
        )
    with fiona.open(footprints) as src:
        assert len(src) == 2


def test_reprediction_writes_fresh_matching_outputs(tmp_path, footprints):
    first = write(
        tmp_path, footprints, [{"id": i, "damaged": 0} for i in range(2)]
    )
    second = write(
        tmp_path,
        footprints,
        [{"id": i, "damaged": 1} for i in range(2)],
        revision="run-2",
    )
    assert second.payload["predictionRevision"] == "run-2"
    assert second.payload["classes"] == ["Damaged"] * 2
    assert json.loads((tmp_path / "run-1.json").read_text()) == first.payload


def test_sidecar_failure_propagates(tmp_path, footprints, mocker):
    mocker.patch(
        "hastegeo.core.processors.building_predictions.write_prediction_attrs",
        side_effect=OSError("disk full"),
    )
    with pytest.raises(OSError):
        write(
            tmp_path, footprints, [{"id": i, "damaged": 0} for i in range(2)]
        )


def test_empty_footprints_produce_valid_empty_artifacts(tmp_path):
    fp = write_gpkg(tmp_path / "footprints.gpkg", [], fields={"id": "str"})
    result = write(tmp_path, fp, [])
    assert result.count == 0
    assert result.payload["classes"] == []
    with fiona.open(result.gpkg_path) as src:
        assert len(src) == 0
        assert src.crs.to_epsg() == 6933
