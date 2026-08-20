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


def _point_box(x, y, size=1.0):
    """A small square centered near (x, y)."""
    return shapely.geometry.box(x, y, x + size, y + size)


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

    def test_ids_are_stable_across_calls(self):
        """Cluster ids come from enumeration order, which must be repeatable."""
        features = [_point_box(x, y) for x in (5, 45) for y in (5, 45)]
        bounds = shapely.geometry.box(0, 0, 100, 100)

        first = assign_features_to_grid(features, bounds, 50.0)
        second = assign_features_to_grid(features, bounds, 50.0)

        self.assertEqual([idx for _, idx in first], [idx for _, idx in second])


if __name__ == "__main__":
    unittest.main()
