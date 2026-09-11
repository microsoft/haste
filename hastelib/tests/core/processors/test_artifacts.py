# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from hastegeo.core.processors.artifacts import ArtifactProcessor


class TestArtifactProcessor:
    def test_fetch_artifact_delegates_to_storage(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.storage = mocker.Mock()
        processor.storage.fetch_artifact.return_value = "/tmp/output"

        result = processor.fetch_artifact(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )

        assert result == "/tmp/output"
        processor.storage.fetch_artifact.assert_called_once_with(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )
