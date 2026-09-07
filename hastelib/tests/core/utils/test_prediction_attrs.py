# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Test the public raw sidecar contract with native GeoPackages."""

import json

import fiona
import pytest
from hastegeo.core.utils.prediction_attrs import (
    FootprintPredictionMismatchError,
    attrs_artifact_name,
    build_prediction_attrs,
    write_prediction_attrs,
)

from ..prediction_fixtures import (
    PREDICTION_FIELDS,
    prediction_rows,
    write_gpkg,
    write_pair,
)


def build(footprints, predictions, **kwargs):
    return build_prediction_attrs(
        predictions, footprints, prediction_revision="run-1", **kwargs
    )


@pytest.mark.parametrize("embedding", [False, True])
@pytest.mark.parametrize("damages", [(0.0, 1.0), (0.0,), (1.0,), ()])
def test_flavor_uses_schema_including_binary_and_empty(
    tmp_path, embedding, damages
):
    fp, pred = write_pair(
        tmp_path, prediction_rows(damages), embedding=embedding
    )
    payload = build(fp, pred)
    assert payload["flavor"] == ("embedding" if embedding else "inference")
    assert payload["n"] == len(damages)
    assert all(
        len(value) == len(damages)
        for value in payload.values()
        if isinstance(value, list)
    )


@pytest.mark.parametrize("flavor", ["embedding", "unknown"])
def test_explicit_flavor_must_match_schema(tmp_path, flavor):
    fp, pred = write_pair(tmp_path, prediction_rows())
    with pytest.raises(ValueError, match="flavor"):
        build(fp, pred, flavor=flavor)


def test_json_roundtrip_preserves_identity_nulls_classes_and_precision(
    tmp_path,
):
    rows = prediction_rows(
        [0.0, 0.25, 1e-10, None, float("nan"), float("inf"), 0.8, 0.0],
        [0.0, 0.0, 0.0, None, 0.0, float("-inf"), 0.1, 1e-10],
    )
    fp, pred = write_pair(tmp_path, rows)
    output = tmp_path / "attrs.json"
    payload = write_prediction_attrs(
        pred,
        fp,
        str(output),
        prediction_revision="run-1",
        footprint_fingerprint="optional-source",
    )
    assert json.loads(output.read_text()) == payload
    json.dumps(payload, allow_nan=False)
    assert payload["schemaVersion"] == 1
    assert payload["predictionRevision"] == "run-1"
    assert payload["footprintFingerprint"] == "optional-source"
    assert payload["ids"] == list(range(8))
    assert payload["overtureIds"] == [f"building-{i}" for i in range(8)]
    assert payload["damage"] == [0.0, 0.25, 1e-10, None, None, None, 0.8, 0.0]
    assert payload["unknown"] == [0.0, 0.0, 0.0, None, 0.0, None, 0.1, 1e-10]
    assert (
        payload["classes"]
        == ["NotDamaged", "Damaged", "Damaged"] + ["Unknown"] * 5
    )
    assert payload["damaged"] == [row["damaged"] for row in rows]
    assert "footprintFingerprint" not in build(fp, pred)


@pytest.mark.parametrize(
    "field,values,field_type",
    [
        ("id", [1, 0], "int"),
        ("id", [0, 0], "int"),
        ("id", [0, 2], "int"),
        ("id", [-1, 0], "int"),
        ("id", ["0", "1"], "str"),
        ("id", [0.0, 1.0], "float"),
        ("overture_id", ["building-1", "building-0"], "str"),
        ("overture_id", ["same", "same"], "str"),
        ("overture_id", [None, "building-1"], "str"),
        ("overture_id", ["", "building-1"], "str"),
    ],
)
def test_stored_prediction_identity_cannot_be_reenumerated(
    tmp_path, field, values, field_type
):
    rows = prediction_rows()
    fp, pred = write_pair(tmp_path, rows)
    for row, value in zip(rows, values):
        row[field] = value
    write_gpkg(
        tmp_path / "predictions.gpkg",
        rows,
        fields={**PREDICTION_FIELDS, field: field_type},
    )
    with pytest.raises(FootprintPredictionMismatchError):
        build(fp, pred)


@pytest.mark.parametrize(
    "ids",
    [
        ["building-0"],
        ["building-0", "building-1", "building-2"],
        ["building-1", "building-0"],
        ["other-0", "other-1"],
        ["same", "same"],
    ],
)
def test_footprint_count_order_and_identity_must_match(tmp_path, ids):
    fp, pred = write_pair(tmp_path, prediction_rows())
    write_gpkg(
        tmp_path / "footprints.gpkg",
        [{"id": value} for value in ids],
        fields={"id": "str"},
    )
    with pytest.raises(FootprintPredictionMismatchError):
        build(fp, pred)


@pytest.mark.parametrize("missing", list(PREDICTION_FIELDS))
def test_required_prediction_columns_cannot_be_defaulted(tmp_path, missing):
    rows = prediction_rows()
    fp, pred = write_pair(tmp_path, rows)
    write_gpkg(
        tmp_path / "predictions.gpkg",
        rows,
        fields={k: v for k, v in PREDICTION_FIELDS.items() if k != missing},
    )
    with pytest.raises(ValueError, match="missing columns"):
        build(fp, pred)


@pytest.mark.parametrize("footprints", [False, True])
def test_crs_is_required_for_both_sources(tmp_path, footprints):
    fp, pred = write_pair(tmp_path, prediction_rows())
    if footprints:
        write_gpkg(
            tmp_path / "footprints.gpkg",
            [{"id": f"building-{i}"} for i in range(2)],
            fields={"id": "str"},
            crs=None,
        )
    else:
        write_gpkg(tmp_path / "predictions.gpkg", prediction_rows(), crs=None)
    with pytest.raises(ValueError, match="CRS"):
        build(fp, pred)


@pytest.mark.parametrize(
    "field,value",
    [
        ("damage_pct_0m", -0.1),
        ("damage_pct_0m", 1.1),
        ("unknown_pct", -0.1),
        ("unknown_pct", 1.1),
        ("damaged", 2),
    ],
)
def test_invalid_scores_are_not_silently_coerced(tmp_path, field, value):
    rows = prediction_rows()
    rows[0][field] = value
    fp, pred = write_pair(tmp_path, rows)
    with pytest.raises(ValueError):
        build(fp, pred)


def test_bad_revision_write_failure_and_input_aliases_propagate(tmp_path):
    fp, pred = write_pair(tmp_path, prediction_rows())
    with pytest.raises(ValueError):
        build_prediction_attrs(pred, fp, prediction_revision="")
    with pytest.raises(OSError):
        write_prediction_attrs(
            pred, fp, str(tmp_path), prediction_revision="run-1"
        )
    for path in (fp, pred):
        with pytest.raises(ValueError):
            write_prediction_attrs(pred, fp, path, prediction_revision="run-1")
        with fiona.open(path) as src:
            assert len(src) == 2


@pytest.mark.parametrize("model_id", ["", "../1234", "1/2"])
def test_artifact_name_is_a_safe_reference_basename(model_id):
    assert attrs_artifact_name("5557") == "prediction_attrs_5557.json"
    with pytest.raises(ValueError):
        attrs_artifact_name(model_id)


def test_missing_unknown_score_stays_unknown(tmp_path):
    fp, pred = write_pair(tmp_path, prediction_rows([0.0], [None]))
    assert build(fp, pred)["classes"] == ["Unknown"]
