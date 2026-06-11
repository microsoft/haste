# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the imageryprep workflow's building-footprint step.

The full workflow exercises GDAL/rasterio against real GeoTIFFs, so these
tests focus on the new ``ImageryWorkflow.download_building_footprints()``
step in isolation by mocking out the AOI extractor and the subprocess that
runs the actual Overture download. The goals:

- (a) the prefix/filename uses the BUILDING_FOOTPRINTS ArtifactType template
  substituted with the layer's IDs;
- (b) the subprocess invocation passes the right CLI args;
- (c) any subprocess failure (non-zero exit, timeout, SIGSEGV) does not
  raise out of ``download_building_footprints`` — instead the failure is
  captured on ``building_footprints_error`` so the parent workflow can
  still finish writing the manifest, and ImageryPostProcessor can mark
  the image layer FAILED in the UI with that message;
- (d) the step records an error when no post-event mosaic is present
  rather than silently no-oping;
- (e) the AOI polygon is persisted as the valid-area-mask GeoJSON file
  so the UI can offer it as a downloadable artifact.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import shapely.geometry
from hastegeo.workflows.prepare_imagery import ImageryWorkflow


def _fake_polygon():
    """A small shapely polygon to stand in for extract_aoi_polygon()."""
    return shapely.geometry.Polygon(
        [
            (-156.70, 20.87),
            (-156.66, 20.87),
            (-156.66, 20.89),
            (-156.70, 20.89),
        ]
    )


class TestDownloadBuildingFootprintsStep(unittest.TestCase):
    """Unit tests for ImageryWorkflow.download_building_footprints()."""

    def _make_workflow(self, dst_directory):
        wf = ImageryWorkflow(
            project_id="proj-1",
            image_layer_id="layer-9",
            dst_directory=dst_directory,
        )
        # Pretend process_post_event ran and populated the mosaic path.
        # The path doesn't have to be a real COG because we mock the AOI
        # extractor; it just needs to exist so the existence check passes.
        mosaic = os.path.join(dst_directory, "fake_post_event_mosaic.tif")
        with open(mosaic, "wb") as f:
            f.write(b"")
        wf.mosaic_post_event_tif_filepath = mosaic
        return wf

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_writes_gpkg_with_layer_keyed_filename(
        self, mock_polygon, mock_run
    ):
        mock_polygon.return_value = _fake_polygon()

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            expected_path = os.path.join(
                tmp, "building_footprints_proj-1_layer-9.gpkg"
            )

            # Have the "subprocess" actually create the output file so the
            # path-existence check inside download_building_footprints passes.
            def fake_run(cmd, **_):
                with open(expected_path, "wb") as f:
                    f.write(b"GPKG-stub")
                return MagicMock(returncode=0, stdout="42\n", stderr="")

            mock_run.side_effect = fake_run

            wf.download_building_footprints()

            self.assertEqual(wf.building_footprints_path, expected_path)
            self.assertEqual(wf.building_footprints_error, "")
            mock_polygon.assert_called_once_with(
                wf.mosaic_post_event_tif_filepath
            )
            # Subprocess called with the expected CLI shape
            self.assertTrue(mock_run.called)
            cmd = mock_run.call_args.args[0]
            self.assertIn("hastegeo.core.utils.footprints", cmd)
            # Bbox derived from the polygon's bounds
            self.assertIn("--bbox=-156.7,20.87,-156.66,20.89", cmd)
            self.assertIn("--output-path", cmd)
            self.assertIn(expected_path, cmd)
            self.assertIn("--overwrite", cmd)
            # The AOI geojson was saved before the subprocess ran, so
            # its path should be forwarded to the downloader for
            # corner-cropping the bbox-only Overture result.
            mask_path = os.path.join(
                tmp, "valid_area_mask_proj-1_layer-9.geojson"
            )
            self.assertIn(f"--aoi-geojson={mask_path}", cmd)

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_writes_valid_area_mask_geojson(self, mock_polygon, mock_run):
        # The AOI polygon should be persisted to a GeoJSON file using the
        # VALID_AREA_MASK prefix so the UI can offer it for download.
        polygon = _fake_polygon()
        mock_polygon.return_value = polygon
        mock_run.return_value = MagicMock(
            returncode=0, stdout="0\n", stderr=""
        )

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            expected_mask = os.path.join(
                tmp, "valid_area_mask_proj-1_layer-9.geojson"
            )
            # Subprocess "succeeds" by creating the gpkg.
            with open(
                os.path.join(tmp, "building_footprints_proj-1_layer-9.gpkg"),
                "wb",
            ) as f:
                f.write(b"GPKG-stub")

            wf.download_building_footprints()

            self.assertEqual(wf.valid_area_mask_path, expected_mask)
            self.assertEqual(wf.valid_area_mask_error, "")
            self.assertTrue(os.path.exists(expected_mask))
            with open(expected_mask) as f:
                fc = json.load(f)
            self.assertEqual(fc["type"], "FeatureCollection")
            self.assertEqual(len(fc["features"]), 1)
            self.assertEqual(fc["features"][0]["geometry"]["type"], "Polygon")

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_mask_survives_footprint_subprocess_failure(
        self, mock_polygon, mock_run
    ):
        # Mask is written before the subprocess runs, so a subprocess
        # failure should still leave the mask in place.
        mock_polygon.return_value = _fake_polygon()
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="boom"
        )

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()

            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("exit code 1", wf.building_footprints_error)
            # Mask was extracted/saved before the subprocess ran.
            self.assertTrue(wf.valid_area_mask_path)
            self.assertTrue(os.path.exists(wf.valid_area_mask_path))
            self.assertEqual(wf.valid_area_mask_error, "")

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_subprocess_nonzero_exit_records_error(
        self, mock_polygon, mock_run
    ):
        mock_polygon.return_value = _fake_polygon()
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="boom",
        )

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("exit code 1", wf.building_footprints_error)
            self.assertIn("boom", wf.building_footprints_error)

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_subprocess_segfault_records_error(self, mock_polygon, mock_run):
        mock_polygon.return_value = _fake_polygon()
        # SIGSEGV manifests as returncode -11 from subprocess.run
        mock_run.return_value = MagicMock(
            returncode=-11,
            stdout="",
            stderr="qemu: uncaught target signal 11",
        )

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("exit code -11", wf.building_footprints_error)

    @patch("subprocess.run")
    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_subprocess_timeout_records_error(self, mock_polygon, mock_run):
        mock_polygon.return_value = _fake_polygon()
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["python"], timeout=1
        )

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("timed out", wf.building_footprints_error)

    @patch("hastegeo.core.utils.aoi.extract_aoi_polygon")
    def test_aoi_failure_records_error(self, mock_polygon):
        mock_polygon.side_effect = RuntimeError("rasterio could not open")
        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("area-of-interest", wf.building_footprints_error)
            # The same AOI failure also bubbles into the mask error so
            # the UI can surface a clear cause for the missing mask.
            self.assertEqual(wf.valid_area_mask_path, "")
            self.assertIn("area-of-interest", wf.valid_area_mask_error)

    def test_skips_when_no_post_event_mosaic_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = ImageryWorkflow(
                project_id="proj-1",
                image_layer_id="layer-9",
                dst_directory=tmp,
            )
            # No mosaic path set
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")
            self.assertIn("post-event mosaic", wf.building_footprints_error)
            self.assertEqual(wf.valid_area_mask_path, "")
            self.assertIn("post-event mosaic", wf.valid_area_mask_error)


if __name__ == "__main__":
    unittest.main()
