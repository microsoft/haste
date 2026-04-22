# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from hastegeo.core.processors.artifacts import ArtifactProcessor


class TestArtifactProcessor:
    def test_zip(self, mocker):
        # Arrange
        blob_service_client = BlobServiceClient.from_connection_string(
            os.environ.get("BLOB_CONNECTION_STRING")
        )
        try:
            container_client = blob_service_client.create_container(
                os.getenv("BLOB_CONTAINER")
            )
        except ResourceExistsError:
            container_client = blob_service_client.get_container_client(
                os.getenv("BLOB_CONTAINER")
            )
        except Exception as e:
            print(e)

        test_artifacts = {
            "folder1": ["test1.txt", "test2.txt"],
            "folder2": ["test3.txt", "test4.txt"],
        }

        for folder in test_artifacts.keys():
            for file in test_artifacts[folder]:
                file_path = os.path.join(folder, file)
                blob_client = container_client.get_blob_client(file_path)
                blob_client.upload_blob(
                    r"This is a test file.", overwrite=True
                )

        model_id = "1234"
        model_name = "test_model_name"

        # Act
        processor = ArtifactProcessor()
        result = processor.zip(
            artifact_paths=["folder1", "folder2"],
            zip_path=f"model_{model_id}_artifacts/{model_name}.zip",
        )

        # Assertions
        assert result == f"model_{model_id}_artifacts/{model_name}.zip"
        expected_blob_client = container_client.get_blob_client(result)
        assert expected_blob_client.exists() is True
