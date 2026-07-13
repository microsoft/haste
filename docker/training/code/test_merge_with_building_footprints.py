# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for ``merge_with_building_footprints.py``.

Focus: the CRS-aware metric buffering used when merging damage
predictions with building footprints. The regression these tests guard
against is buffering a *geographic* (EPSG:4326, degrees) prediction
raster by a metre distance directly, which balloons the footprint by
tens of degrees and either crashes or yields nonsensical damage
fractions.

The test builds tiny synthetic fixtures with rasterio / geopandas (no
hand-rolled raster or vector bytes) and drives the script's ``main``
entrypoint plus its pure helpers.
"""

import argparse
import os
import sys
import tempfile
import unittest

import fiona
import geopandas as gpd
import numpy as np
import rasterio
import shapely.geometry
from rasterio.transform import from_origin

# The script under test lives next to this file and is not installed as a
# package, so make it importable by path.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import merge_with_building_footprints as merge  # noqa: E402


def _write_raster(path, arr, crs, transform):
    """Write a single-band uint8 raster with rasterio."""
    height, width = arr.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(arr, 1)


def _damage_array():
    """A 40x40 label array: class-2 ring around a class-3 damaged core.

    The concentric layout means a *metrically correct* buffer picks up
    progressively more class-2 pixels, so the damaged fraction strictly
    decreases from 0 m -> 10 m -> 20 m. A degrees-based buffer instead
    swallows the whole raster at both 10 and 20, collapsing those two
    values to the same number -- which is exactly what the fix prevents.
    """
    arr = np.zeros((40, 40), dtype="uint8")
    arr[15:26, 15:26] = 2  # surrounding (undamaged) pixels
    arr[19:22, 19:22] = 3  # damaged core
    return arr


def _core_polygon(origin_x, origin_y, px, py):
    """Polygon covering the 3x3 damaged core (rows/cols 19..21)."""
    x0 = origin_x + 19 * px
    x1 = origin_x + 22 * px
    # ``py`` is the (positive) pixel height; rows increase downward.
    y_top = origin_y - 19 * py
    y_bot = origin_y - 22 * py
    return shapely.geometry.box(x0, y_bot, x1, y_top)


def _write_footprints(path, polygon, crs):
    """Write a one-row footprints GeoPackage with geopandas."""
    gdf = gpd.GeoDataFrame({"id": [0]}, geometry=[polygon], crs=crs)
    gdf.to_file(path, driver="GPKG")


def _read_output(path):
    """Return the list of feature property dicts from an output GPKG."""
    with fiona.open(path) as src:
        return [dict(feat["properties"]) for feat in src]


class MetricCrsForTest(unittest.TestCase):
    """Unit tests for :func:`metric_crs_for`."""

    def test_geographic_returns_utm(self):
        # A point off the US west coast -> UTM zone 10N (EPSG:32610).
        bounds = (-122.400, 37.698, -122.396, 37.702)
        self.assertEqual(
            merge.metric_crs_for("EPSG:4326", bounds), "EPSG:32610"
        )

    def test_geographic_southern_hemisphere_returns_326xx(self):
        # Sydney-ish -> UTM zone 56S (EPSG:32756).
        bounds = (151.20, -33.87, 151.22, -33.85)
        self.assertEqual(
            merge.metric_crs_for("EPSG:4326", bounds), "EPSG:32756"
        )

    def test_projected_returns_input_unchanged(self):
        # Projected CRS units are already metres -> no round-trip needed.
        bounds = (500000.0, 4170000.0, 500400.0, 4170400.0)
        self.assertEqual(
            merge.metric_crs_for("EPSG:32610", bounds), "EPSG:32610"
        )


class BufferedShapeTest(unittest.TestCase):
    """Unit tests for :func:`buffered_shape`."""

    def test_projected_matches_direct_shapely_buffer(self):
        # When metric_crs == predictions_crs the helper must be a no-op
        # wrapper around shapely.buffer -> zero behaviour change.
        poly = shapely.geometry.box(0, 0, 10, 10)
        geom = shapely.geometry.mapping(poly)
        got = merge.buffered_shape(geom, "EPSG:32610", "EPSG:32610", 10)
        expected = shapely.geometry.shape(geom).buffer(10)
        self.assertTrue(got.equals(expected))

    def test_geographic_buffer_is_metric(self):
        # Buffer a ~10 m building by 20 m in EPSG:4326; the reprojected,
        # buffered footprint should measure ~20 m of growth in UTM, not
        # ~20 degrees.
        poly = _core_polygon(-122.4000, 37.7020, 0.0001, 0.0001)
        geom = shapely.geometry.mapping(poly)
        metric = "EPSG:32610"
        buffered = merge.buffered_shape(geom, "EPSG:4326", metric, 20)
        # Reproject both to UTM and compare bounding-box growth.
        base_m = gpd.GeoSeries([poly], crs="EPSG:4326").to_crs(metric)
        buf_m = gpd.GeoSeries([buffered], crs="EPSG:4326").to_crs(metric)
        b0 = base_m.total_bounds
        b1 = buf_m.total_bounds
        grow_left = b0[0] - b1[0]
        grow_right = b1[2] - b0[2]
        # ~20 m of growth per side (tolerate projection/rounding slack).
        self.assertAlmostEqual(grow_left, 20.0, delta=3.0)
        self.assertAlmostEqual(grow_right, 20.0, delta=3.0)

    def test_geographic_buffer_zero_is_noop(self):
        poly = _core_polygon(-122.4000, 37.7020, 0.0001, 0.0001)
        geom = shapely.geometry.mapping(poly)
        got = merge.buffered_shape(geom, "EPSG:4326", "EPSG:32610", 0)
        expected = shapely.geometry.shape(geom).buffer(0)
        self.assertTrue(got.equals(expected))


class MainIntegrationTest(unittest.TestCase):
    """End-to-end runs of :func:`main` for geographic and projected CRS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run_main(self, predictions_fn, footprints_fn):
        output_fn = os.path.join(self.tmp, "merged.gpkg")
        args = argparse.Namespace(
            footprints_fn=footprints_fn,
            predictions_fn=predictions_fn,
            output_fn=output_fn,
            overwrite=True,
        )
        merge.main(args)
        return output_fn

    def test_geographic_epsg4326_does_not_crash_and_computes(self):
        # --- Fixture: EPSG:4326 raster + overlapping footprint. ---
        arr = _damage_array()
        west, north, px = -122.4000, 37.7020, 0.0001
        transform = from_origin(west, north, px, px)
        pred_fn = os.path.join(self.tmp, "pred_4326.tif")
        _write_raster(pred_fn, arr, "EPSG:4326", transform)

        poly = _core_polygon(west, north, px, px)
        fp_fn = os.path.join(self.tmp, "fp_4326.gpkg")
        _write_footprints(fp_fn, poly, "EPSG:4326")

        # (a) does not crash
        output_fn = self._run_main(pred_fn, fp_fn)

        # (b) output produced with the one valid building geom
        self.assertTrue(os.path.exists(output_fn))
        rows = _read_output(output_fn)
        self.assertEqual(len(rows), 1)

        # (c) buffered damage percentages computed and metrically sane:
        # 0 m fully damaged, then strictly decreasing as the metric buffer
        # pulls in surrounding class-2 pixels. Under the (buggy) degrees
        # buffer, 10 m and 20 m collapse to the same value.
        props = rows[0]
        d0 = props["damage_pct_0m"]
        d10 = props["damage_pct_10m"]
        d20 = props["damage_pct_20m"]
        for val in (d0, d10, d20):
            self.assertTrue(np.isfinite(val))
        self.assertAlmostEqual(d0, 1.0, places=6)
        self.assertLess(d10, d0)
        self.assertLess(d20, d10)
        self.assertIn("unknown_pct", props)

    def test_projected_utm_unchanged(self):
        # --- Fixture: EPSG:32610 (metre) raster + footprint. ---
        arr = _damage_array()
        origin_x, origin_y, px = 500000.0, 4170000.0, 10.0
        transform = from_origin(origin_x, origin_y, px, px)
        pred_fn = os.path.join(self.tmp, "pred_utm.tif")
        _write_raster(pred_fn, arr, "EPSG:32610", transform)

        poly = _core_polygon(origin_x, origin_y, px, px)
        fp_fn = os.path.join(self.tmp, "fp_utm.gpkg")
        _write_footprints(fp_fn, poly, "EPSG:32610")

        output_fn = self._run_main(pred_fn, fp_fn)

        self.assertTrue(os.path.exists(output_fn))
        rows = _read_output(output_fn)
        self.assertEqual(len(rows), 1)
        props = rows[0]
        self.assertAlmostEqual(props["damage_pct_0m"], 1.0, places=6)
        self.assertLess(props["damage_pct_10m"], props["damage_pct_0m"])
        self.assertLess(props["damage_pct_20m"], props["damage_pct_10m"])


if __name__ == "__main__":
    unittest.main()
