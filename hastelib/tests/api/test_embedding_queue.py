# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import json
import os

import pytest

os.environ.setdefault("DATA_PATH", "/tmp/haste-api-tests")

queue_app = pytest.importorskip("hastefuncqueues.function_app")


def _queue_message(mocker, body):
    message = mocker.Mock()
    message.get_body.return_value = body
    return message


def test_embedding_value_error_persists_failed_model(mocker):
    model = queue_app.Model(
        projectId="project-id",
        modelId="model-id",
        imageLayerId="layer-id",
        modelType="embedding",
        embeddingModel="dinov3_sat",
        status="pending",
    )
    image_layer = queue_app.ImageLayer(
        projectId="project-id",
        imageLayerId="layer-id",
    )
    metadata = mocker.patch.object(queue_app, "MetadataProcessor")
    metadata.return_value.load.side_effect = [
        {"modelId": "model-id"},
        image_layer.dict(),
    ]
    postprocessor = mocker.patch.object(queue_app, "EmbeddingPostprocessor")
    postprocessor.return_value.process.side_effect = ValueError(
        "DINOV3_SAT_MODEL_BLOB_PREFIX must be configured"
    )
    message = _queue_message(mocker, json.dumps(model.dict()).encode("utf-8"))
    handler = (
        queue_app.GetRunEmbeddingQueueMessage._function.get_user_function()
    )

    asyncio.run(handler(message))

    save_call = metadata.return_value.save.call_args
    assert save_call.args[0] == "model-id"
    saved_model = save_call.args[1]
    assert (
        saved_model["status"]
        == queue_app.config.get_status_types().FAILED.value
    )
    assert "Embedding job failed" in saved_model["statusMessage"]
    assert "DINOV3_SAT_MODEL_BLOB_PREFIX" in saved_model["statusMessage"]


def test_embedding_invalid_json_does_not_attempt_model_persistence(mocker):
    metadata = mocker.patch.object(queue_app, "MetadataProcessor")
    postprocessor = mocker.patch.object(queue_app, "EmbeddingPostprocessor")
    message = _queue_message(mocker, b"{invalid-json")
    handler = (
        queue_app.GetRunEmbeddingQueueMessage._function.get_user_function()
    )

    asyncio.run(handler(message))

    metadata.assert_not_called()
    postprocessor.assert_not_called()
