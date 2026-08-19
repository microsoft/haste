# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import logging
from types import SimpleNamespace

from hastegeo.core.runners.local import LocalRunner
from hastegeo.core.runners.resource_files import redact_resource_files
from hastegeo.core.runners.unified_runner import UnifiedRunner


def _resources():
    return {
        "config": {
            "http_url": (
                "https://models.example/container/config.json"
                "?sv=1&sig=secret-value#credential"
            ),
            "file_path": "inputs/config.json",
        }
    }


def test_resource_file_redaction_does_not_mutate_actual_resources():
    resources = _resources()

    safe_resources = redact_resource_files(resources)

    assert "secret-value" not in str(safe_resources)
    assert "credential" not in str(safe_resources)
    assert "REDACTED" in str(safe_resources)
    assert "sig=secret-value" in resources["config"]["http_url"]


def test_unified_runner_logs_redacted_resource_urls(caplog, mocker):
    runner = UnifiedRunner.__new__(UnifiedRunner)
    runner.runner = mocker.Mock()
    resources = _resources()

    with caplog.at_level(
        logging.INFO, logger="hastegeo.core.runners.unified_runner"
    ):
        runner.add_task(
            "job-id",
            "task-id",
            resource_files_for_upload=resources,
        )

    assert "secret-value" not in caplog.text
    assert "credential" not in caplog.text
    assert "REDACTED" in caplog.text
    runner.runner.add_task.assert_called_once_with(
        "job-id",
        "task-id",
        resource_files_for_upload=resources,
    )


def test_local_runner_logs_redacted_resource_urls(mocker):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    resources = _resources()

    runner._log_resource_files(resources)

    logged_message = runner.logger.info.call_args.args[0]
    assert "secret-value" not in logged_message
    assert "credential" not in logged_message
    assert "REDACTED" in logged_message
    assert "sig=secret-value" in resources["config"]["http_url"]


def test_local_prefix_download_exception_does_not_log_secret(tmp_path, mocker):
    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()
    runner.blob_client = mocker.Mock()
    container_client = runner.blob_client.get_container_client.return_value
    container_client.list_blobs.return_value = [
        SimpleNamespace(name="models/snapshot/config.json")
    ]
    container_client.download_blob.side_effect = RuntimeError(
        "request failed at https://models/container?sig=secret"
    )
    resources = {
        "model": {
            "storage_container_url": (
                "https://models/container?sig=container-secret"
            ),
            "blob_prefix": "models/snapshot",
            "file_path": "inputs",
        }
    }

    runner._download_resource_files(tmp_path, resources)

    logged_messages = " ".join(
        str(call.args[0]) for call in runner.logger.error.call_args_list
    )
    assert "secret" not in logged_messages
    assert "model" in logged_messages
    assert "models/snapshot" in logged_messages
    assert "RuntimeError" in logged_messages


def test_local_outer_resource_exception_does_not_log_secret(mocker):
    class BrokenResources(dict):
        def items(self):
            raise RuntimeError("SDK failure at ?sig=secret")

    runner = LocalRunner.__new__(LocalRunner)
    runner.logger = mocker.Mock()

    runner._download_resource_files(None, BrokenResources())

    logged_message = runner.logger.error.call_args.args[0]
    assert "secret" not in logged_message
    assert "RuntimeError" in logged_message
