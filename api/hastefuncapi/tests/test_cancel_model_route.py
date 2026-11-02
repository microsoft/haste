import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-cancel-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-cancel-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

from hastegeo.core.config import Config  # noqa: E402
from hastegeo.core.models.projects import Model  # noqa: E402
from hastegeo.core.processors.metadata import MetadataProcessor  # noqa: E402

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
MODEL_ID = "42"
STATUS = Config.get_status_types()


def cancel_request() -> func.HttpRequest:
    return func.HttpRequest(
        method="PUT",
        url="http://localhost/api/PutCancelModelQueueMessage",
        headers={},
        params={},
        route_params={},
        body=json.dumps({"projectId": PROJECT_ID, "modelId": MODEL_ID}).encode(
            "utf-8"
        ),
    )


class TestCancelModelRoute(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(
            os.environ,
            {"METADATA_STORAGE_TYPE": "local", "DATA_PATH": directory.name},
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.models = MetadataProcessor(
            data_type=Config.get_metadata_types().MODEL.value,
            partition_key=PROJECT_ID,
        )

    def store(self, **fields: str) -> None:
        model = Model(
            modelId=MODEL_ID,
            projectId=PROJECT_ID,
            imageLayerId="layer-1",
            name="Damage model",
            maxEpochs="1",
            statusMessage="",
            inferenceStatusMessage="",
            **fields,
        )
        self.models.save(MODEL_ID, model.model_dump(mode="json"))

    async def test_no_effect_notices_are_persisted(self) -> None:
        cases = [
            (
                {"status": STATUS.FAILED.value},
                "statusMessage",
                "Training already failed, Cancel action has no effect",
            ),
            (
                {
                    "status": STATUS.COMPLETED.value,
                    "inferenceStatus": STATUS.COMPLETED.value,
                },
                "inferenceStatusMessage",
                "Inference already completed, Cancel action has no effect",
            ),
            (
                {
                    "status": STATUS.COMPLETED.value,
                    "inferenceStatus": STATUS.FAILED.value,
                },
                "inferenceStatusMessage",
                "Inference already failed, Cancel action has no effect",
            ),
        ]
        for fields, field, notice in cases:
            with self.subTest(notice=notice):
                self.store(**fields)

                response = await function_app.PutCancelModelQueueMessage(
                    cancel_request()
                )

                self.assertEqual(response.status_code, 200)
                stored = self.models.load(MODEL_ID)
                self.assertTrue(stored[field].endswith(f": {notice}"))
                self.assertEqual(
                    json.loads(response.get_body())[field], stored[field]
                )


if __name__ == "__main__":
    unittest.main()
