import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-validation-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-validation-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
LAYER_ID = "550e8400-e29b-41d4-a716-446655440000"


def make_request(body: dict | None = None) -> func.HttpRequest:
    encoded = json.dumps(body).encode("utf-8") if body is not None else b""
    return func.HttpRequest(
        method="PUT",
        url="http://localhost/api/validation",
        headers={},
        params={},
        route_params={},
        body=encoded,
    )


def response_json(response: func.HttpResponse) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


def make_label(building_id: str) -> dict:
    return {
        "id": building_id,
        "label": "Damaged",
        "updatedAt": "2026-08-22T00:00:00Z",
    }


class ValidationRouteTestCase(unittest.IsolatedAsyncioTestCase):
    """Shared harness: a fake BuildingValidationProcessor."""

    def setUp(self) -> None:
        self.processor = Mock()
        self.processor.save.side_effect = lambda v: v.model_dump()
        patcher = patch.object(
            function_app,
            "BuildingValidationProcessor",
            return_value=self.processor,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def stored(self, **overrides) -> dict:
        document = {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "labels": {},
            "sampleSize": 200,
        }
        document.update(overrides)
        self.processor.load.return_value = document
        return document

    def saved_document(self) -> dict:
        self.processor.save.assert_called_once()
        return self.processor.save.call_args.args[0].model_dump()


class TestPutBuildingValidation(ValidationRouteTestCase):
    """Label saves must not disturb the configured sample size."""

    async def test_label_save_preserves_the_configured_sample_size(
        self,
    ) -> None:
        """The regression this feature has to avoid.

        The validation view saves {projectId, imageLayerId, labels} and this
        route replaces the document wholesale, so an unguarded sampleSize
        would be filled with the model default and silently reset the user's
        setting on every save. Same failure mode as PR #135.
        """
        self.stored(sampleSize=500)

        response = await function_app.PutBuildingValidation(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "labels": {"bldg-1": make_label("bldg-1")},
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 500)
        self.assertEqual(response_json(response)["sampleSize"], 500)

    async def test_label_save_on_a_layer_with_no_document(self) -> None:
        """A layer nobody has configured falls back to the default."""
        self.processor.load.return_value = None

        response = await function_app.PutBuildingValidation(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "labels": {},
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 200)

    async def test_explicit_sample_size_is_written(self) -> None:
        """An explicit value wins, and the stored one is not consulted."""
        self.stored(sampleSize=500)

        response = await function_app.PutBuildingValidation(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "labels": {},
                    "sampleSize": 300,
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 300)
        self.processor.load.assert_not_called()

    async def test_clearing_labels_keeps_the_sample_size(self) -> None:
        """Clear is a save with an empty label set."""
        self.stored(sampleSize=500, labels={"a": make_label("a")})

        response = await function_app.PutBuildingValidation(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "labels": {},
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        saved = self.saved_document()
        self.assertEqual(saved["labels"], {})
        self.assertEqual(saved["sampleSize"], 500)

    async def test_requires_identifiers(self) -> None:
        response = await function_app.PutBuildingValidation(
            make_request({"labels": {}})
        )

        self.assertEqual(response.status_code, 400)


class TestPutBuildingValidationConfig(ValidationRouteTestCase):
    """The count-change rules."""

    async def _put(self, sample_size, **stored_overrides):
        self.stored(**stored_overrides)
        return await function_app.PutBuildingValidationConfig(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "sampleSize": sample_size,
                }
            )
        )

    async def test_raising_the_count_is_allowed_with_labels_present(
        self,
    ) -> None:
        """Growing never destroys work: the sample only extends."""
        response = await self._put(
            300, sampleSize=200, labels={"a": make_label("a")}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 300)

    async def test_raising_the_count_keeps_existing_labels(self) -> None:
        labels = {"a": make_label("a"), "b": make_label("b")}

        response = await self._put(300, sampleSize=200, labels=labels)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["labels"], labels)

    async def test_lowering_the_count_is_allowed_without_labels(self) -> None:
        response = await self._put(100, sampleSize=300, labels={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 100)

    async def test_lowering_the_count_is_refused_with_labels(self) -> None:
        """409, not 400: the request is valid once labels are cleared."""
        response = await self._put(
            100, sampleSize=300, labels={"a": make_label("a")}
        )

        self.assertEqual(response.status_code, 409)
        self.processor.save.assert_not_called()

    async def test_refusal_explains_what_to_do(self) -> None:
        response = await self._put(
            100, sampleSize=300, labels={"a": make_label("a")}
        )

        self.assertIn(
            "Clear the validation labels first",
            response_json(response)["error"],
        )

    async def test_unchanged_count_writes_nothing(self) -> None:
        response = await self._put(
            200, sampleSize=200, labels={"a": make_label("a")}
        )

        self.assertEqual(response.status_code, 200)
        self.processor.save.assert_not_called()
        self.assertEqual(response_json(response)["sampleSize"], 200)

    async def test_layer_with_no_document_compares_against_the_default(
        self,
    ) -> None:
        self.processor.load.return_value = None

        response = await function_app.PutBuildingValidationConfig(
            make_request(
                {
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                    "sampleSize": 400,
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved_document()["sampleSize"], 400)

    async def test_rejects_out_of_range_values(self) -> None:
        for bad in [0, -1, 2001]:
            with self.subTest(bad=bad):
                self.processor.save.reset_mock()
                response = await self._put(bad, sampleSize=200)

                self.assertEqual(response.status_code, 400)
                self.processor.save.assert_not_called()

    async def test_rejects_non_integer_values(self) -> None:
        for bad in ["300", 12.5, None]:
            with self.subTest(bad=bad):
                self.processor.save.reset_mock()
                response = await self._put(bad, sampleSize=200)

                self.assertEqual(response.status_code, 400)
                self.processor.save.assert_not_called()

    async def test_requires_identifiers(self) -> None:
        response = await function_app.PutBuildingValidationConfig(
            make_request({"sampleSize": 300})
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
