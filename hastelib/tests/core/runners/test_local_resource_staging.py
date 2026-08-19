# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from types import SimpleNamespace

import pytest
from hastegeo.core.processors.artifacts import ArtifactProcessor
from hastegeo.core.runners.local import LocalRunner


def test_exact_url_resources_stage_at_direct_file_paths(tmp_path, mocker):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()

    def candidates(blob_url):
        candidate = mocker.Mock()
        download = mocker.Mock()
        download.readinto.side_effect = lambda stream: stream.write(
            blob_url.encode()
        )
        candidate.download_blob.return_value = download
        return [candidate]

    runner._build_blob_client_candidates = mocker.Mock(side_effect=candidates)
    resources = {
        "config": {
            "http_url": "https://models/container/prefix/config.json",
            "file_path": "inputs/models/dinov3_sat/config.json",
        },
        "weights": {
            "http_url": ("https://models/container/prefix/model.safetensors"),
            "file_path": "inputs/models/dinov3_sat/model.safetensors",
        },
    }

    runner._download_resource_files(tmp_path, resources)

    model_dir = tmp_path / "inputs/models/dinov3_sat"
    assert (model_dir / "config.json").read_bytes().endswith(b"config.json")
    assert (
        (model_dir / "model.safetensors")
        .read_bytes()
        .endswith(b"model.safetensors")
    )


def test_container_prefix_resources_preserve_full_blob_hierarchy(
    tmp_path, mocker
):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    container_client.list_blobs.return_value = [
        SimpleNamespace(name="models/snapshot/config.json"),
        SimpleNamespace(name="models/snapshot/nested/model.safetensors"),
    ]

    def download_blob(blob_name):
        payload = blob_name.encode()
        download = mocker.Mock()
        download.readinto.side_effect = lambda stream: stream.write(payload)
        return download

    container_client.download_blob.side_effect = download_blob
    resources = {
        "model": {
            "storage_container_url": "https://account.blob/core/models",
            "blob_prefix": "models/snapshot",
            "file_path": "inputs/models/dinov3_sat",
        }
    }

    runner._download_resource_files(tmp_path, resources)

    destination = tmp_path / "inputs/models/dinov3_sat/models/snapshot"
    assert (destination / "config.json").read_bytes() == (
        b"models/snapshot/config.json"
    )
    assert (destination / "nested/model.safetensors").read_bytes() == (
        b"models/snapshot/nested/model.safetensors"
    )
    container_client.list_blobs.assert_called_once_with(
        name_starts_with="models/snapshot/"
    )


def test_container_prefix_nested_blob_retains_existing_path(tmp_path, mocker):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    container_client.list_blobs.return_value = [
        SimpleNamespace(name="project/trn-task/checkpoint/model.ckpt")
    ]
    download = mocker.Mock()
    download.readinto.side_effect = lambda stream: stream.write(b"checkpoint")
    container_client.download_blob.return_value = download
    resources = {
        "training": {
            "storage_container_url": "https://account.blob/core/artifacts",
            "blob_prefix": "project/trn-task",
            "file_path": "inputs",
        }
    }

    runner._download_resource_files(tmp_path, resources)

    assert (
        tmp_path / "inputs/project/trn-task/checkpoint/model.ckpt"
    ).read_bytes() == b"checkpoint"


def test_artifact_prefix_resources_retain_existing_task_directory(mocker):
    processor = ArtifactProcessor.__new__(ArtifactProcessor)
    processor.storage = mocker.Mock()
    processor.storage.get_base_url.return_value = (
        "https://account.blob/core/artifacts"
    )
    processor.model_data = SimpleNamespace(
        trainingOutputPath="project/trn-task",
        inferenceOutputPath="project/inf-task",
    )

    resources = processor.prepare_zip_job()

    assert resources["training"]["file_path"] == "inputs/"
    assert resources["inference"]["file_path"] == "inputs/"


@pytest.mark.parametrize("resource_type", ["http", "prefix"])
@pytest.mark.parametrize(
    "file_path", ["/tmp/escape", "../escape", "C:\\escape"]
)
def test_resource_file_path_rejects_absolute_or_traversal_paths(
    tmp_path, mocker, resource_type, file_path
):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = None
    if resource_type == "http":
        resource = {
            "http_url": "https://account.blob/core/data/file.json",
            "file_path": file_path,
        }
    else:
        resource = {
            "storage_container_url": "https://account.blob/core/data",
            "blob_prefix": "models/snapshot",
            "file_path": file_path,
        }

    with pytest.raises(ValueError, match="destination directory"):
        runner._download_resource_files(tmp_path, {"resource": resource})


@pytest.mark.parametrize("resource_type", ["http", "prefix"])
def test_resource_file_path_rejects_symlink_escape(
    tmp_path, mocker, resource_type
):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (task_dir / "linked").symlink_to(outside, target_is_directory=True)
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    if resource_type == "http":
        resource = {
            "http_url": "https://account.blob/core/data/file.json",
            "file_path": "linked/file.json",
        }
    else:
        resource = {
            "storage_container_url": "https://account.blob/core/data",
            "blob_prefix": "models/snapshot",
            "file_path": "linked/model",
        }

    with pytest.raises(ValueError, match="outside"):
        runner._download_resource_files(task_dir, {"resource": resource})


@pytest.mark.parametrize(
    "blob_name",
    [
        "models/snapshot/../../escape",
        "/tmp/escape",
        "models/snapshot/C:\\escape",
    ],
)
def test_container_prefix_rejects_unsafe_blob_names(
    tmp_path, mocker, blob_name
):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    container_client.list_blobs.return_value = [
        SimpleNamespace(name=blob_name)
    ]
    resources = {
        "model": {
            "storage_container_url": "https://account.blob/core/models",
            "blob_prefix": "models/snapshot",
            "file_path": "inputs",
        }
    }

    with pytest.raises(ValueError, match="Resource blob name"):
        runner._download_resource_files(tmp_path, resources)

    container_client.download_blob.assert_not_called()


def test_container_prefix_rejects_blob_symlink_escape(tmp_path, mocker):
    destination = tmp_path / "inputs"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (destination / "models").symlink_to(outside, target_is_directory=True)
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    container_client.list_blobs.return_value = [
        SimpleNamespace(name="models/snapshot/config.json")
    ]
    resources = {
        "model": {
            "storage_container_url": "https://account.blob/core/models",
            "blob_prefix": "models/snapshot",
            "file_path": "inputs",
        }
    }

    with pytest.raises(ValueError, match="outside"):
        runner._download_resource_files(tmp_path, resources)

    container_client.download_blob.assert_not_called()


def test_container_prefix_excludes_sibling_prefix(tmp_path, mocker):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    valid_name = "models/snapshot/config.json"
    sibling_name = "models/snapshot-sibling/weights.bin"
    container_client.list_blobs.return_value = [
        SimpleNamespace(name=valid_name),
        SimpleNamespace(name=sibling_name),
    ]
    download = mocker.Mock()
    download.readinto.side_effect = lambda stream: stream.write(b"config")
    container_client.download_blob.return_value = download
    resources = {
        "model": {
            "storage_container_url": "https://account.blob/core/models",
            "blob_prefix": "models/snapshot",
            "file_path": "inputs",
        }
    }

    runner._download_resource_files(tmp_path, resources)

    assert (
        tmp_path / "inputs/models/snapshot/config.json"
    ).read_bytes() == b"config"
    assert not (
        tmp_path / "inputs/models/snapshot-sibling/weights.bin"
    ).exists()
    container_client.list_blobs.assert_called_once_with(
        name_starts_with="models/snapshot/"
    )
    container_client.download_blob.assert_called_once_with(valid_name)
