# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from types import SimpleNamespace

import pytest
from hastegeo.core.processors import embedding
from hastegeo.core.processors.embedding import EmbeddingPostprocessor
from hastegeo.core.utils.metadata import MetadataUtils


def _processor(mocker, embedding_model, prefix=None, container_url=None):
    project_id = "project-id"
    project_hash = MetadataUtils.hash_string(project_id)
    processor = EmbeddingPostprocessor.__new__(EmbeddingPostprocessor)
    processor.model_data = SimpleNamespace(
        projectId=project_id,
        imageLayerId="layer-id",
        modelId="model-id",
        embeddingModel=embedding_model,
        numFeatures=1024,
        resizeFactor=1,
        batchSize=1,
    )
    processor.image_layer = SimpleNamespace(
        postEventMosaicCogImageryUrl=(
            f"https://storage/data/{project_hash}/image.tif?sig=test"
        ),
        buildingFootprintsUrl=(
            f"https://storage/data/{project_hash}/footprints.gpkg?sig=test"
        ),
    )
    metadata_type = SimpleNamespace(value="embedding_config")
    processor.config = SimpleNamespace(
        DINOV3_SAT_MODEL_BLOB_PREFIX=prefix,
        DINOV3_SAT_MODEL_CONTAINER_URL=container_url,
        get_metadata_types=lambda: SimpleNamespace(
            EMBEDDING_CONFIG=metadata_type
        ),
    )
    processor.storage = mocker.Mock()
    processor.storage.get_base_url.return_value = "https://storage/data"
    processor.storage.get_file_remote_path.return_value = (
        f"https://storage/data/{project_hash}/config.json?sig=test"
    )
    processor.artifact_storage = mocker.Mock()
    processor.artifact_storage.get_base_url.return_value = (
        "https://artifacts/models"
    )
    return processor


def test_dinov3_sat_config_stages_local_model_snapshot(mocker):
    processor = _processor(
        mocker,
        "dinov3_sat",
        prefix="models/dinov3/snapshot",
        container_url="https://models/container",
    )

    resources = processor._create_embedding_config()

    assert resources["dinov3_sat_config"] == {
        "http_url": (
            "https://models/container/models/dinov3/snapshot/config.json"
        ),
        "file_path": "inputs/models/dinov3_sat/config.json",
    }
    assert resources["dinov3_sat_weights"] == {
        "http_url": (
            "https://models/container/models/dinov3/snapshot/"
            "model.safetensors"
        ),
        "file_path": "inputs/models/dinov3_sat/model.safetensors",
    }
    saved_config = processor.storage.save.call_args.kwargs["data"]
    assert saved_config["files"]["model"] == "inputs/models/dinov3_sat"
    processor.artifact_storage.get_base_url.assert_not_called()


def test_dinov3_sat_config_defaults_to_artifact_container(mocker):
    processor = _processor(
        mocker, "dinov3_sat", prefix="models/dinov3/snapshot"
    )

    resources = processor._create_embedding_config()

    assert resources["dinov3_sat_config"]["http_url"] == (
        "https://artifacts/models/models/dinov3/snapshot/config.json"
    )
    assert resources["dinov3_sat_weights"]["http_url"] == (
        "https://artifacts/models/models/dinov3/snapshot/model.safetensors"
    )
    processor.artifact_storage.get_base_url.assert_called_once_with()
    processor.storage.get_base_url.assert_not_called()


def test_dinov3_sat_model_urls_encode_prefix_segments(mocker):
    processor = _processor(
        mocker,
        "dinov3_sat",
        prefix="/approved/DINOv3 SAT/snapshot%20one/",
        container_url="https://models.blob.core.windows.net/gated",
    )

    resources = processor._create_embedding_config()

    assert resources["dinov3_sat_config"]["http_url"] == (
        "https://models.blob.core.windows.net/gated/approved/"
        "DINOv3%20SAT/snapshot%20one/config.json"
    )
    assert resources["dinov3_sat_weights"]["http_url"] == (
        "https://models.blob.core.windows.net/gated/approved/"
        "DINOv3%20SAT/snapshot%20one/model.safetensors"
    )


@pytest.mark.parametrize(
    "container_url",
    [
        "https://models/container?sv=1&sig=secret",
        "https://models/container#secret",
        "http://models/container",
        "https:///container",
    ],
)
def test_dinov3_sat_rejects_non_bare_https_container_url(
    mocker, container_url
):
    processor = _processor(
        mocker,
        "dinov3_sat",
        prefix="approved/snapshot",
        container_url=container_url,
    )

    with pytest.raises(ValueError, match="bare HTTPS container URL"):
        processor._create_embedding_config()

    processor.storage.save.assert_not_called()


@pytest.mark.parametrize("prefix", ["../snapshot", "%2E%2E/snapshot"])
def test_dinov3_sat_model_urls_reject_traversal_prefix(mocker, prefix):
    processor = _processor(
        mocker,
        "dinov3_sat",
        prefix=prefix,
        container_url="https://models/container",
    )

    with pytest.raises(ValueError, match="traversal"):
        processor._create_embedding_config()

    processor.storage.save.assert_not_called()


def test_embedding_postprocessor_initializes_separate_artifact_storage(mocker):
    metadata_storage = mocker.patch.object(embedding, "UnifiedDataLayer")
    artifact_storage = mocker.patch.object(embedding, "UnifiedArtifactStorage")
    mocker.patch.object(embedding, "UnifiedRunner")
    mocker.patch.object(embedding, "AzureQueueHandler")
    config = SimpleNamespace(
        storage_type="cosmos",
        storage_config={"database": "metadata"},
        artifact_storage_type="blob",
        artifact_storage_config={"container": "model-artifacts"},
        runner_type="local",
        queue_config={
            "queue_connection_string": None,
            "embedding_queue_name": "embedding",
            "queue_account_url": None,
        },
        get_azure_batch_config=lambda: {
            "training_pool_id": "training",
            "training_pool_ids": ["training"],
        },
    )
    model = SimpleNamespace(projectId="project-id")

    processor = EmbeddingPostprocessor(model=model, config=config)

    metadata_storage.assert_called_once_with(
        storage_type="cosmos",
        partition_key="project-id",
        database="metadata",
    )
    artifact_storage.assert_called_once_with(
        storage_type="blob",
        partition_key="project-id",
        container="model-artifacts",
    )
    assert processor.storage is metadata_storage.return_value
    assert processor.artifact_storage is artifact_storage.return_value


def test_dinov3_sat_config_rejects_missing_blob_prefix(mocker):
    processor = _processor(mocker, "dinov3_sat", prefix="  ")

    with pytest.raises(ValueError, match="DINOV3_SAT_MODEL_BLOB_PREFIX"):
        processor._create_embedding_config()

    processor.storage.save.assert_not_called()


@pytest.mark.parametrize("embedding_model", ["mosaiks", "dinov2_vitl14"])
def test_existing_model_config_does_not_add_model_resource(
    mocker, embedding_model
):
    processor = _processor(mocker, embedding_model)

    resources = processor._create_embedding_config()

    assert set(resources) == {"config", "imagery", "footprints"}
    saved_config = processor.storage.save.call_args.kwargs["data"]
    assert "model" not in saved_config["files"]
    processor.storage.get_base_url.assert_not_called()
    processor.artifact_storage.get_base_url.assert_not_called()
