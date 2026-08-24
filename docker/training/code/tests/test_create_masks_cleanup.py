# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for output cleanup in ``create_masks.py``.

``SegmentationDataModule`` loads every TIFF it finds in ``images/``, so any
pair left over from an earlier run silently joins the new training set. Two
paths can leave one behind: ``--overwrite`` only replaced the pairs the
current run regenerates, and a cluster skipped mid-write left partial files
plus intermediates that would trip the next attempt's ``ogr2ogr``.
"""

import os
import sys
import tempfile
import unittest

# The script under test lives in the parent directory and is not installed
# as a package, so make it importable by path.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)


def _load_cleanup_helpers():
    """Load the cleanup helpers without create_masks' GDAL dependencies."""
    import glob as glob_module

    path = os.path.join(CODE_DIR, "create_masks.py")
    with open(path) as f:
        source = f.read()

    start = source.index("def artifact_paths(")
    end = source.index("def validate_cluster_crs(")
    namespace = {"os": os, "glob": glob_module}
    exec(compile(source[start:end], path, "exec"), namespace)
    return namespace


_helpers = _load_cleanup_helpers()
artifact_paths = _helpers["artifact_paths"]
remove_files = _helpers["remove_files"]
remove_previous_outputs = _helpers["remove_previous_outputs"]


class TestArtifactPaths(unittest.TestCase):
    def test_unclustered_names(self):
        paths = artifact_paths("/exp", "scene", "")
        self.assertTrue(paths["image"].endswith("images/scene_cropped.tif"))
        self.assertTrue(paths["mask"].endswith("masks/scene_buffered.tif"))

    def test_clustered_names(self):
        paths = artifact_paths("/exp", "scene", "_cluster_7")
        self.assertTrue(
            paths["image"].endswith("images/scene_cluster_7_cropped.tif")
        )
        self.assertTrue(
            paths["mask"].endswith("masks/scene_cluster_7_buffered.tif")
        )


class TestRemovePreviousOutputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "images"))
        os.makedirs(os.path.join(self.root, "masks"))

    def _touch(self, relpath):
        path = os.path.join(self.root, relpath)
        with open(path, "w") as f:
            f.write("x")
        return path

    def test_removes_stale_cluster_pairs(self):
        """The case that mixes old tiles into a new run's training set."""
        stale = [
            self._touch("images/scene_cluster_0_cropped.tif"),
            self._touch("images/scene_cluster_1_cropped.tif"),
            self._touch("masks/scene_cluster_0_buffered.tif"),
            self._touch("masks/scene_cluster_1_buffered.tif"),
        ]

        remove_previous_outputs(self.root, "scene")

        for path in stale:
            self.assertFalse(os.path.exists(path), path)

    def test_removes_unclustered_pair(self):
        """Switching clustering on must not strand the single-pair output."""
        stale = [
            self._touch("images/scene_cropped.tif"),
            self._touch("masks/scene_buffered.tif"),
        ]

        remove_previous_outputs(self.root, "scene")

        for path in stale:
            self.assertFalse(os.path.exists(path), path)

    def test_removes_leftover_intermediates(self):
        """Aborted runs leave these, and ogr2ogr won't overwrite the GeoJSON."""
        stale = [
            self._touch("scene_cluster_0_labels_warped.geojson"),
            self._touch("scene_cluster_0_mask.tif"),
        ]

        remove_previous_outputs(self.root, "scene")

        for path in stale:
            self.assertFalse(os.path.exists(path), path)

    def test_leaves_other_images_alone(self):
        """A different image whose name shares a prefix must survive."""
        keep = [
            self._touch("images/scene2_cropped.tif"),
            self._touch("images/scene2_cluster_0_cropped.tif"),
            self._touch("masks/scene2_cluster_0_buffered.tif"),
            self._touch("images/other_cluster_0_cropped.tif"),
        ]

        remove_previous_outputs(self.root, "scene")

        for path in keep:
            self.assertTrue(os.path.exists(path), path)

    def test_leaves_the_label_backup_alone(self):
        os.makedirs(os.path.join(self.root, "labels"))
        keep = self._touch("labels/scene.geojson")

        remove_previous_outputs(self.root, "scene")

        self.assertTrue(os.path.exists(keep))

    def test_is_a_noop_on_a_clean_directory(self):
        remove_previous_outputs(self.root, "scene")  # must not raise


class TestRemoveFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ignores_missing_paths(self):
        present = os.path.join(self.tmp.name, "here.tif")
        with open(present, "w") as f:
            f.write("x")
        missing = os.path.join(self.tmp.name, "gone.tif")

        remove_files([present, missing, None])

        self.assertFalse(os.path.exists(present))


if __name__ == "__main__":
    unittest.main()
