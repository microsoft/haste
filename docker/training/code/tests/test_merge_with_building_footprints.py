# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native metric-buffer, stable-row and empty-COG regression tests."""

import argparse
import json
import sys
from pathlib import Path

import fiona
import numpy as np
import pytest
import rasterio
from hastegeo.core.utils.prediction_attrs import write_prediction_attrs
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as project

from hastelib.tests.core.prediction_fixtures import write_gpkg, write_raster

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import merge_with_building_footprints as merge  # noqa: E402
import output2visualizer as visualizer  # noqa: E402

TRANSFORM = from_origin(500000, 4170400, 10, 10)
CORE = box(500190, 4170180, 500220, 4170210)
OUTSIDE = box(500500, 4170100, 500520, 4170120)


def run_merge(
    directory,
    geometries,
    values,
    *,
    transform=TRANSFORM,
    crs="EPSG:32610",
    footprint_crs="EPSG:32610",
    nodata=0,
    mask=None,
):
    fp = write_gpkg(
        directory / "footprints.gpkg",
        [{"id": f"building-{i}"} for i in range(len(geometries))],
        fields={"id": "str"},
        geometries=geometries,
        crs=footprint_crs,
    )
    raster = write_raster(
        directory / "raw.tif", values, transform, crs=crs, nodata=nodata
    )
    if mask is not None:
        with rasterio.open(raster, "r+") as dst:
            dst.write_mask(mask)
    gpkg = str(directory / "merged.gpkg")
    merge.main(
        argparse.Namespace(
            footprints_fn=fp,
            predictions_fn=raster,
            output_fn=gpkg,
            overwrite=True,
        )
    )
    payload = write_prediction_attrs(
        gpkg,
        fp,
        str(directory / "attrs.json"),
        prediction_revision="run-1",
        flavor="inference",
    )
    assert json.loads((directory / "attrs.json").read_text()) == payload
    return payload


def run_visualizer(directory):
    visualizer.main(
        argparse.Namespace(
            predictions_fn=str(directory / "raw.tif"),
            merged_footprints_fn=str(directory / "merged.gpkg"),
            output_fn=str(directory / "visualizer.tif"),
            overwrite=True,
        )
    )
    return rasterio.open(directory / "visualizer.tif")


@pytest.mark.parametrize(
    "crs,bounds,expected",
    [
        ("EPSG:4326", (-122.400, 37.698, -122.396, 37.702), "EPSG:32610"),
        ("EPSG:4326", (151.20, -33.87, 151.22, -33.85), "EPSG:32756"),
        ("EPSG:32610", (500000, 4170000, 500400, 4170400), "EPSG:32610"),
    ],
)
def test_metric_crs_handles_both_hemispheres_and_projected_input(
    crs, bounds, expected
):
    assert merge.metric_crs_for(crs, bounds) == expected


def test_buffer_distances_are_metres_not_degrees():
    polygon = box(-122.4, 37.7, -122.3999, 37.7001)
    buffered = merge.buffered_shape(
        mapping(polygon), "EPSG:4326", "EPSG:32610", 20
    )
    to_utm = Transformer.from_crs(4326, 32610, always_xy=True).transform
    original_bounds = project(to_utm, polygon).bounds
    buffered_bounds = project(to_utm, buffered).bounds
    assert original_bounds[0] - buffered_bounds[0] == pytest.approx(20, abs=3)
    assert buffered_bounds[2] - original_bounds[2] == pytest.approx(20, abs=3)
    assert merge.buffered_shape(
        mapping(polygon), "EPSG:4326", "EPSG:32610", 0
    ).equals(polygon.buffer(0))
    assert merge.buffered_shape(
        mapping(CORE), "EPSG:32610", "EPSG:32610", 10
    ).equals(CORE.buffer(10))


@pytest.mark.parametrize(
    "crs,transform",
    [
        ("EPSG:32610", TRANSFORM),
        ("EPSG:4326", from_origin(-122.4000, 37.7020, 0.0001, 0.0001)),
    ],
)
def test_native_merge_preserves_crs_and_metric_buffer_scores(
    tmp_path, crs, transform
):
    values = np.zeros((40, 40), dtype="uint8")
    values[15:26, 15:26] = 2
    values[19:22, 19:22] = 3
    left, top = transform * (19, 19)
    right, bottom = transform * (22, 22)
    polygon = box(left, bottom, right, top)
    run_merge(
        tmp_path,
        [polygon],
        values,
        transform=transform,
        crs=crs,
        footprint_crs=crs,
    )
    with fiona.open(tmp_path / "merged.gpkg") as src:
        assert src.crs.to_string() == crs
        row = next(iter(src))
        assert shape(row["geometry"]).equals(polygon)
        props = row["properties"]
        assert props["damage_pct_0m"] == pytest.approx(1)
        assert 0 <= props["damage_pct_20m"] < props["damage_pct_10m"] < 1
        assert props["unknown_pct"] == 0


def test_outside_nodata_and_null_rows_never_shift_scored_identity(tmp_path):
    values = np.full((40, 40), 2, dtype="uint8")
    values[19:22, 19:22] = 3
    values[30:, :10] = 0
    payload = run_merge(
        tmp_path,
        [OUTSIDE, CORE, box(500000, 4170000, 500100, 4170100), None],
        values,
    )
    assert payload["ids"] == [0, 1, 2, 3]
    assert payload["overtureIds"] == [f"building-{i}" for i in range(4)]
    assert payload["damage"] == [None, 1.0, None, None]
    assert payload["unknown"] == [None, 0.0, None, None]
    assert payload["classes"] == ["Unknown", "Damaged", "Unknown", "Unknown"]
    with fiona.open(tmp_path / "merged.gpkg") as src:
        rows = list(src)
        assert src.crs.to_epsg() == 32610
    assert [row["properties"]["id"] for row in rows] == [0, 1, 2, 3]
    assert shape(rows[1]["geometry"]).equals(CORE)
    assert rows[3]["geometry"] is None
    for index in (0, 2, 3):
        assert rows[index]["properties"]["damage_pct_10m"] is None
        assert rows[index]["properties"]["damage_pct_20m"] is None
    with run_visualizer(tmp_path) as src:
        assert src.transform == TRANSFORM
        assert src.crs.to_epsg() == 32610
        assert src.read(4)[20, 20] == 255
        assert src.read(4)[35, 5] == 0


@pytest.mark.parametrize("masked", [False, True])
def test_raster_masks_and_nonzero_nodata_remain_unscored(tmp_path, masked):
    payload = run_merge(
        tmp_path,
        [CORE],
        np.full((40, 40), 3 if masked else 255, dtype="uint8"),
        nodata=0 if masked else 255,
        mask=np.zeros((40, 40), dtype="uint8") if masked else None,
    )
    assert payload["damage"] == [None]
    assert payload["classes"] == ["Unknown"]


def test_reprojection_preserves_ids_and_actual_geometry(tmp_path):
    geographic = project(
        Transformer.from_crs(32610, 4326, always_xy=True).transform, CORE
    )
    payload = run_merge(
        tmp_path,
        [geographic],
        np.full((40, 40), 3, dtype="uint8"),
        footprint_crs="EPSG:4326",
    )
    assert payload["overtureIds"] == ["building-0"]
    assert payload["classes"] == ["Damaged"]
    with fiona.open(tmp_path / "merged.gpkg") as src:
        assert src.crs.to_epsg() == 32610
        assert (
            shape(next(iter(src))["geometry"]).hausdorff_distance(CORE) < 0.001
        )


def test_empty_outputs_are_transparent_valid_cogs(tmp_path):
    payload = run_merge(tmp_path, [], np.zeros((1024, 1024), dtype="uint8"))
    assert payload["n"] == 0 and payload["classes"] == []
    with run_visualizer(tmp_path) as src:
        assert not src.read().any()
        assert src.transform == TRANSFORM
        assert src.crs.to_epsg() == 32610
        assert src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert src.compression.value == "LZW"
        assert src.block_shapes == [(512, 512)] * 4
        assert src.overviews(1)


def test_unscored_and_cloud_rows_are_transparent(tmp_path):
    payload = run_merge(
        tmp_path, [OUTSIDE, CORE], np.full((40, 40), 4, dtype="uint8")
    )
    assert payload["classes"] == ["Unknown", "Unknown"]
    assert payload["unknown"] == [None, 1.0]
    with run_visualizer(tmp_path) as src:
        assert not src.read().any()


def test_missing_and_mismatched_raster_crs_fail(tmp_path):
    values = np.zeros((40, 40), dtype="uint8")
    with pytest.raises(ValueError, match="CRS"):
        run_merge(tmp_path, [CORE], values, crs=None)
    assert not (tmp_path / "merged.gpkg").exists()
    run_merge(tmp_path, [CORE], values)
    write_raster(tmp_path / "raw.tif", values, TRANSFORM, crs="EPSG:3857")
    with pytest.raises(ValueError, match="CRS differ"):
        run_visualizer(tmp_path)
