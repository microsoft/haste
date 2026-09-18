# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""The imagery download cap has to travel to the Batch task.

``ImageryDownloader`` runs inside the imageryprep container, not in any
Function App, so ``HASTE_MAX_IMAGERY_DOWNLOAD_BYTES`` only takes effect if
``ImageryPostProcessor`` forwards it as a task environment setting. Without
that, tuning the app setting silently does nothing and the container keeps
using the code default.
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class _StopAfterAddTask(Exception):
    pass


class TestImageryDownloadCapPropagation(unittest.TestCase):
    def _add_task_kwargs(self):
        from hastegeo.core.models.projects import ImageLayer

        image_data = MagicMock(spec=ImageLayer)
        image_data.projectId = "proj-1"
        image_data.imageLayerId = "layer-9"
        image_data.preEventImageryUrls = ["https://example/pre.tif"]
        image_data.postEventImageryUrls = ["https://example/post.tif"]
        image_data.sourceTypePreEvent = "url"
        image_data.sourceTypePostEvent = "url"
        image_data.autoFineTune = False
        image_data.userBuildingFootprintsUrl = None
        image_data.clipBbox = None

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

        processor.storage.save = MagicMock()
        # The config path is run through a regex to split blob path from SAS,
        # so it has to be a real string rather than the autospec MagicMock.
        from hastegeo.core.utils.metadata import MetadataUtils

        proj_hash = MetadataUtils.hash_string("proj-1")
        processor.storage.get_file_remote_path = MagicMock(
            return_value=(
                f"https://x.blob.core.windows.net/c/{proj_hash}/"
                "imagery_config.yaml?sv=x&sig=y"
            )
        )
        # Stop at the submission boundary: everything after add_task writes
        # job bookkeeping onto the spec'd ImageLayer mock and is not under test.
        captured = {}

        def fake_add_task(**kwargs):
            captured.update(kwargs)
            raise _StopAfterAddTask()

        processor.runner.add_task = MagicMock(side_effect=fake_add_task)
        try:
            processor._execute_image_preprocess()
        except _StopAfterAddTask:
            pass
        return captured

    def test_forwards_the_configured_cap_to_the_batch_task(self):
        with patch.dict(
            os.environ,
            {"HASTE_MAX_IMAGERY_DOWNLOAD_BYTES": "32212254720"},
        ):
            kwargs = self._add_task_kwargs()

        self.assertEqual(
            kwargs["env_vars"]["HASTE_MAX_IMAGERY_DOWNLOAD_BYTES"],
            "32212254720",
        )

    def test_forwards_the_code_default_when_unset(self):
        env = dict(os.environ)
        env.pop("HASTE_MAX_IMAGERY_DOWNLOAD_BYTES", None)
        with patch.dict(os.environ, env, clear=True):
            kwargs = self._add_task_kwargs()

        # 8 GiB — the gdal_security default.
        self.assertEqual(
            kwargs["env_vars"]["HASTE_MAX_IMAGERY_DOWNLOAD_BYTES"],
            str(8 * 1024**3),
        )


if __name__ == "__main__":
    unittest.main()
