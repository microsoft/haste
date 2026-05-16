# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the imageryprep workflow's building-footprint step.

The full workflow exercises GDAL/rasterio against real GeoTIFFs, so these
tests focus on the new ``ImageryWorkflow.download_building_footprints()``
step in isolation by mocking out the AOI extractor and Overture downloader.
The goal is to verify (a) the prefix/filename uses the BUILDING_FOOTPRINTS
ArtifactType template substituted with the layer's IDs, and (b) Overture
failures are non-fatal (``building_footprints_path`` left empty so the
manifest entry is empty).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from hastegeo.workflows.prepare_imagery import ImageryWorkflow


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

    @patch("hastegeo.core.utils.footprints.download_building_footprints")
    @patch("hastegeo.core.utils.aoi.aoi_bbox_from_cog")
    def test_writes_gpkg_with_layer_keyed_filename(
        self, mock_bbox, mock_download
    ):
        mock_bbox.return_value = (-156.7, 20.87, -156.66, 20.89)
        mock_download.return_value = 42

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            wf.download_building_footprints()

            expected_path = os.path.join(
                tmp, "building_footprints_proj-1_layer-9.gpkg"
            )
            self.assertEqual(wf.building_footprints_path, expected_path)

            mock_bbox.assert_called_once_with(
                wf.mosaic_post_event_tif_filepath
            )
            mock_download.assert_called_once_with(
                bbox=(-156.7, 20.87, -156.66, 20.89),
                output_path=expected_path,
                overwrite=True,
            )

    @patch("hastegeo.core.utils.footprints.download_building_footprints")
    @patch("hastegeo.core.utils.aoi.aoi_bbox_from_cog")
    def test_overture_failure_is_non_fatal(self, mock_bbox, mock_download):
        mock_bbox.return_value = (0.0, 0.0, 1.0, 1.0)
        mock_download.side_effect = RuntimeError("Overture went down")

        with tempfile.TemporaryDirectory() as tmp:
            wf = self._make_workflow(tmp)
            # Should not raise — the imageryprep workflow's primary product
            # is the imagery COGs.
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")

    def test_skips_when_no_post_event_mosaic(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = ImageryWorkflow(
                project_id="proj-1",
                image_layer_id="layer-9",
                dst_directory=tmp,
            )
            # No mosaic path set
            wf.download_building_footprints()
            self.assertEqual(wf.building_footprints_path, "")


if __name__ == "__main__":
    unittest.main()
