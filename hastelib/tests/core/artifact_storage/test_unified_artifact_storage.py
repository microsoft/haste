# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import tempfile
import unittest
from unittest.mock import Mock

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)


class TestUnifiedArtifactDownloadUrl(unittest.TestCase):
    def test_forwards_unsigned_flag_to_backend(self) -> None:
        storage = UnifiedArtifactStorage.__new__(UnifiedArtifactStorage)
        storage.artifact_storage = Mock()
        storage.get_download_url(identifier="output.zip", include_sas=False)
        storage.artifact_storage.get_download_url.assert_called_once_with(
            identifier="output.zip",
            artifact_path=None,
            extra_partition_keys=None,
            include_sas=False,
        )

    def test_local_download_accepts_unsigned_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = UnifiedArtifactStorage("local", directory=directory)
            self.assertEqual(
                storage.get_download_url("output.zip", include_sas=False),
                storage.get_download_url("output.zip"),
            )
