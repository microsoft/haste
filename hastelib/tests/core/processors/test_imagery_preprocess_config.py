# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Targeted unit tests for ImageryPostProcessor._execute_image_preprocess.

The full method submits an Azure Batch task; we only need to confirm
that the per-task config dict written to storage (and then read by the
imageryprep container) includes the new ``user_building_footprints_url``
field copied from ``ImageLayer.userBuildingFootprintsUrl``. We do this
by patching ``storage.save`` to raise and inspecting its call args.
"""

import unittest
from unittest.mock import MagicMock, patch


class _StopAfterSave(Exception):
    pass


class TestExecuteImagePreprocessConfigDict(unittest.TestCase):
    def _build_processor(self, *, user_url):
        from hastegeo.core.models.projects import ImageLayer

        image_data = MagicMock(spec=ImageLayer)
        image_data.projectId = "proj-1"
        image_data.imageLayerId = "layer-9"
        image_data.preEventImageryUrls = ["https://example/pre.tif"]
        image_data.postEventImageryUrls = ["https://example/post.tif"]
        image_data.sourceTypePreEvent = "url"
        image_data.sourceTypePostEvent = "url"
        image_data.autoFineTune = False
        image_data.userBuildingFootprintsUrl = user_url

        with patch(
            "hastegeo.core.processors.imagery.UnifiedDataLayer",
            autospec=True,
        ), patch(
            "hastegeo.core.processors.imagery.UnifiedRunner", autospec=True
        ), patch(
            "hastegeo.core.processors.imagery.AzureQueueHandler",
            autospec=True,
        ):
            from hastegeo.core.processors.imagery import ImageryPostProcessor

            processor = ImageryPostProcessor(image_data=image_data)

        return processor

    def _run_and_capture_save(self, user_url):
        processor = self._build_processor(user_url=user_url)
        captured = {}

        def fake_save(**kwargs):
            captured.update(kwargs)
            raise _StopAfterSave()

        processor.storage.save = MagicMock(side_effect=fake_save)
        try:
            processor._execute_image_preprocess()
        except _StopAfterSave:
            pass
        return captured

    def test_config_includes_user_building_footprints_url_when_set(self):
        url = "https://x.blob.core.windows.net/c/f.gpkg?sv=...&sig=..."
        captured = self._run_and_capture_save(user_url=url)
        cfg = captured["data"]
        self.assertIn("user_building_footprints_url", cfg)
        self.assertEqual(cfg["user_building_footprints_url"], url)
        self.assertEqual(cfg["project_id"], "proj-1")
        self.assertEqual(cfg["image_layer_id"], "layer-9")

    def test_config_user_url_is_none_when_unset(self):
        captured = self._run_and_capture_save(user_url=None)
        cfg = captured["data"]
        self.assertIn("user_building_footprints_url", cfg)
        self.assertIsNone(cfg["user_building_footprints_url"])


if __name__ == "__main__":
    unittest.main()
