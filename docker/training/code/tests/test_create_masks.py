# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the label-clustering grid logic in ``create_masks.py``.

``assign_features_to_grid`` is the pure-geometry half of ``cluster_labels``;
testing it directly keeps these tests free of GDAL and of any label file on
disk. The behaviors that matter downstream are: every labeled feature lands in
at least one cell, empty cells are dropped, features straddling a boundary
appear in both neighbours, and cells never extend past the labeled extent (the
cell geometry is what the imagery gets cropped to).
"""

import os
import sys
import unittest

import shapely.geometry

# The script under test lives in the parent directory and is not installed
# as a package, so make it importable by path.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)


def _load_assign_features_to_grid():
    """Import the helper without pulling in create_masks' GDAL dependencies.

    ``create_masks`` imports cv2/fiona/rasterio at module scope, none of which
    this test needs. Exec just the function under test against the modules it
    actually uses.
    """
    import numpy as np

    path = os.path.join(CODE_DIR, "create_masks.py")
    with open(path) as f:
        source = f.read()

    start = source.index("def assign_features_to_grid(")
    end = source.index("def cluster_labels(")
    namespace = {"np": np, "shapely": shapely, "List": list}
    exec(compile(source[start:end], path, "exec"), namespace)
    return namespace["assign_features_to_grid"]


assign_features_to_grid = _load_assign_features_to_grid()


def _load_validate_cluster_crs():
    """Load the CRS gate without importing create_masks' GDAL dependencies."""
    path = os.path.join(CODE_DIR, "create_masks.py")
    with open(path) as f:
        source = f.read()

    start = source.index("def validate_cluster_crs(")
    end = source.index("def assign_features_to_grid(")
    namespace = {}
    exec(compile(source[start:end], path, "exec"), namespace)
    return namespace["validate_cluster_crs"]


validate_cluster_crs = _load_validate_cluster_crs()


def _point_box(x, y, size=1.0):
    """A small square centered near (x, y)."""
    return shapely.geometry.box(x, y, x + size, y + size)


class _FakeCRS:
    """Stands in for a rasterio CRS; only `is_projected` matters here."""

    def __init__(self, name, is_projected):
        self._name = name
        self.is_projected = is_projected

    def to_string(self):
        return self._name


class TestValidateClusterCrs(unittest.TestCase):
    """The grid is built in the imagery's own units.

    On a geographic CRS `cluster_size_in_meters: 1000` means 1000 degrees, so
    every label lands in one cluster and clustering silently does nothing.
    Failing is better than a silent no-op.
    """

    def test_projected_crs_is_accepted(self):
        validate_cluster_crs(_FakeCRS("EPSG:32610", True), "img.tif")

    def test_geographic_crs_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_cluster_crs(_FakeCRS("EPSG:4326", False), "img.tif")
        message = str(ctx.exception)
        self.assertIn("EPSG:4326", message)
        self.assertIn("degrees", message)

    def test_missing_crs_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_cluster_crs(None, "img.tif")
        self.assertIn("no CRS", str(ctx.exception))


class TestCropGeometryOutsideRasterError(unittest.TestCase):
    """The skip path must be narrow enough to only skip empty cells.

    Catching every ValueError swallowed real configuration errors -- the
    too-few-bands check raises one -- once per cluster, and then blamed the
    cluster sizing in the final message.
    """

    def test_is_distinct_from_valueerror(self):
        source = open(os.path.join(CODE_DIR, "create_masks.py")).read()
        namespace = {}
        start = source.index("class CropGeometryOutsideRasterError")
        end = source.index("def _run(")
        exec(compile(source[start:end], "create_masks.py", "exec"), namespace)
        error = namespace["CropGeometryOutsideRasterError"]

        self.assertTrue(issubclass(error, Exception))
        self.assertFalse(issubclass(error, ValueError))
        # ...so `except CropGeometryOutsideRasterError` cannot catch the
        # channel-count ValueError raised elsewhere in the same function.
        self.assertFalse(isinstance(ValueError("x"), error))


class TestAssignFeaturesToGrid(unittest.TestCase):
    def test_single_feature_single_cell(self):
        feature = _point_box(10, 10)
        bounds = shapely.geometry.box(0, 0, 100, 100)

        cells = assign_features_to_grid([feature], bounds, 50.0)

        self.assertEqual(len(cells), 1)
        cell_geom, indices = cells[0]
        self.assertEqual(indices, [0])
        self.assertTrue(cell_geom.contains(feature))

    def test_empty_cells_are_dropped(self):
        """A 100x100 extent at cell size 50 has 4 cells; only 2 are populated."""
        features = [_point_box(10, 10), _point_box(60, 10)]
        bounds = shapely.geometry.box(0, 0, 100, 100)

        cells = assign_features_to_grid(features, bounds, 50.0)

        self.assertEqual(len(cells), 2)
        self.assertEqual(sorted(i for _, idx in cells for i in idx), [0, 1])

    def test_every_feature_is_assigned(self):
        """No labeled feature may be silently dropped by the grid."""
        features = [_point_box(x, y) for x in (5, 45, 85) for y in (5, 45, 85)]
        bounds = shapely.geometry.box(0, 0, 100, 100)

        cells = assign_features_to_grid(features, bounds, 30.0)

        assigned = {i for _, indices in cells for i in indices}
        self.assertEqual(assigned, set(range(len(features))))

    def test_straddling_feature_appears_in_both_cells(self):
        """A polygon crossing a cell boundary is labeled in both tiles."""
        # Cell boundary at x=50; this box spans 45..55.
        feature = shapely.geometry.box(45, 10, 55, 20)
        bounds = shapely.geometry.box(0, 0, 100, 100)

        cells = assign_features_to_grid([feature], bounds, 50.0)

        containing = [c for c in cells if 0 in c[1]]
        self.assertEqual(len(containing), 2)

    def test_cells_do_not_extend_past_label_extent(self):
        """Cell geometry is the imagery crop window, so it must stay in bounds.

        With a 70-unit extent and 50-unit cells the far cells overhang; they
        have to be clipped or create_masks would ask rasterio for imagery
        outside the labeled area.
        """
        features = [_point_box(10, 10), _point_box(60, 60)]
        bounds = shapely.geometry.box(0, 0, 70, 70)

        cells = assign_features_to_grid(features, bounds, 50.0)

        self.assertTrue(cells)
        for cell_geom, _ in cells:
            minx, miny, maxx, maxy = cell_geom.bounds
            self.assertGreaterEqual(minx, 0)
            self.assertGreaterEqual(miny, 0)
            self.assertLessEqual(maxx, 70)
            self.assertLessEqual(maxy, 70)

    def test_no_features_yields_no_cells(self):
        bounds = shapely.geometry.box(0, 0, 100, 100)
        self.assertEqual(assign_features_to_grid([], bounds, 50.0), [])

    def test_cluster_size_larger_than_extent_yields_one_cell(self):
        """A cluster size bigger than the labels collapses to a single tile."""
        features = [_point_box(10, 10), _point_box(20, 20)]
        bounds = shapely.geometry.box(0, 0, 50, 50)

        cells = assign_features_to_grid(features, bounds, 500.0)

        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0][1], [0, 1])

    def test_matches_a_brute_force_scan(self):
        """The STRtree must select exactly what a full scan would.

        `STRtree.query(..., predicate="intersects")` filters to real
        intersections rather than bounding-box candidates, so swapping the
        scan for the index must not change a single assignment. Uses an
        irregular layout with straddling and disjoint geometries.
        """
        features = [
            shapely.geometry.box(5, 5, 8, 8),
            shapely.geometry.box(48, 10, 62, 14),  # straddles x=50
            shapely.geometry.box(10, 48, 14, 62),  # straddles y=50
            shapely.geometry.box(70, 70, 99, 99),  # spans two cells
            shapely.geometry.Point(25, 25).buffer(3),
            shapely.geometry.box(49.5, 49.5, 50.5, 50.5),  # on the corner
        ]
        bounds = shapely.geometry.box(0, 0, 100, 100)
        cluster_size = 25.0

        got = assign_features_to_grid(features, bounds, cluster_size)

        # Independent re-implementation of the loop this replaced.
        minx, miny, maxx, maxy = bounds.bounds
        expected = []
        x = minx
        while x < maxx:
            y = miny
            while y < maxy:
                cell = shapely.geometry.box(
                    x, y, x + cluster_size, y + cluster_size
                )
                idx = [i for i, s in enumerate(features) if cell.intersects(s)]
                if idx:
                    clipped = cell.intersection(bounds.envelope)
                    if not clipped.is_empty:
                        expected.append(idx)
                y += cluster_size
            x += cluster_size

        self.assertEqual([i for _, i in got], expected)

    def test_ids_are_stable_across_calls(self):
        """Cluster ids come from enumeration order, which must be repeatable."""
        features = [_point_box(x, y) for x in (5, 45) for y in (5, 45)]
        bounds = shapely.geometry.box(0, 0, 100, 100)

        first = assign_features_to_grid(features, bounds, 50.0)
        second = assign_features_to_grid(features, bounds, 50.0)

        self.assertEqual([idx for _, idx in first], [idx for _, idx in second])


if __name__ == "__main__":
    unittest.main()
