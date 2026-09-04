# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, patch

import azure.functions as func
from hastegeo.core.utils.async_cache import AsyncTTLCache

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-project-details-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-project-details-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"


def make_request(
    *, include_models: str | None = None, headers: dict | None = None
) -> func.HttpRequest:
    params = {"projectId": PROJECT_ID}
    if include_models is not None:
        params["includeModels"] = include_models
    return func.HttpRequest(
        method="GET",
        url="http://localhost/api/GetProjectDetails",
        headers=headers or {},
        params=params,
        route_params={},
        body=b"",
    )


class TestGetProjectDetails(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = {
            "projectId": PROJECT_ID,
            "name": "Project",
            "imageLayer": [],
            "imageLayerCount": 0,
        }
        self.loader = AsyncMock()
        self.loader.load.return_value = self.project
        patcher = patch.object(
            function_app,
            "ProjectDetailsProcessor",
            return_value=self.loader,
        )
        self.addCleanup(patcher.stop)
        self.processor_class = patcher.start()
        cache_patcher = patch.object(
            function_app,
            "_project_details_cache",
            AsyncTTLCache(ttl_seconds=15, max_entries=8),
        )
        self.addCleanup(cache_patcher.stop)
        cache_patcher.start()

    async def test_returns_project_and_cache_headers(self) -> None:
        response = await function_app.GetProjectDetails(
            make_request(include_models="True")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body()), self.project)
        self.assertEqual(
            response.headers["Cache-Control"], "private, max-age=15"
        )
        self.assertEqual(response.headers["X-Haste-Cache"], "MISS")
        self.assertTrue(response.headers["ETag"].startswith('"'))
        self.processor_class.assert_called_once_with(
            project_id=PROJECT_ID, config=function_app.config
        )
        self.loader.load.assert_awaited_once_with(include_models=True)

    async def test_include_models_defaults_to_false(self) -> None:
        response = await function_app.GetProjectDetails(make_request())

        self.assertEqual(response.status_code, 200)
        self.loader.load.assert_awaited_once_with(include_models=False)

    async def test_matching_etag_returns_empty_304(self) -> None:
        first = await function_app.GetProjectDetails(make_request())
        etag = first.headers["ETag"]
        self.loader.reset_mock()

        response = await function_app.GetProjectDetails(
            make_request(headers={"If-None-Match": etag})
        )

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.get_body(), b"")
        self.assertEqual(response.headers["ETag"], etag)
        self.assertEqual(response.headers["X-Haste-Cache"], "HIT")
        self.loader.load.assert_not_awaited()

    async def test_weak_etag_in_a_list_matches(self) -> None:
        first = await function_app.GetProjectDetails(make_request())
        etag = first.headers["ETag"]

        response = await function_app.GetProjectDetails(
            make_request(headers={"If-None-Match": f'"different", W/{etag}'})
        )

        self.assertEqual(response.status_code, 304)

    async def test_include_models_uses_a_separate_cache_entry(self) -> None:
        await function_app.GetProjectDetails(make_request())
        await function_app.GetProjectDetails(
            make_request(include_models="true")
        )

        self.assertEqual(self.loader.load.await_count, 2)
        self.loader.load.assert_any_await(include_models=False)
        self.loader.load.assert_any_await(include_models=True)

    async def test_no_cache_request_refreshes_cached_response(self) -> None:
        await function_app.GetProjectDetails(make_request())
        self.loader.load.return_value = dict(self.project, name="Updated")

        response = await function_app.GetProjectDetails(
            make_request(headers={"Cache-Control": "no-cache"})
        )
        cached = await function_app.GetProjectDetails(make_request())

        self.assertEqual(json.loads(response.get_body())["name"], "Updated")
        self.assertEqual(json.loads(cached.get_body())["name"], "Updated")
        self.assertEqual(self.loader.load.await_count, 2)

    def test_cache_refresh_directives(self) -> None:
        self.assertTrue(function_app._cache_refresh_requested("no-cache"))
        self.assertTrue(
            function_app._cache_refresh_requested("public, max-age=0")
        )
        self.assertFalse(function_app._cache_refresh_requested("max-age=15"))

    async def test_missing_project_returns_404(self) -> None:
        self.loader.load.side_effect = FileNotFoundError("missing")

        first = await function_app.GetProjectDetails(make_request())
        second = await function_app.GetProjectDetails(make_request())

        self.assertEqual(first.status_code, 404)
        self.assertEqual(second.status_code, 404)
        self.assertEqual(self.loader.load.await_count, 2)

    async def test_unexpected_error_returns_500(self) -> None:
        self.loader.load.side_effect = RuntimeError("storage unavailable")

        response = await function_app.GetProjectDetails(make_request())

        self.assertEqual(response.status_code, 500)

    async def test_invalid_project_id_returns_400_without_loading(
        self,
    ) -> None:
        request = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GetProjectDetails",
            headers={},
            params={"projectId": "not-a-guid"},
            route_params={},
            body=b"",
        )

        response = await function_app.GetProjectDetails(request)

        self.assertEqual(response.status_code, 400)
        self.processor_class.assert_not_called()

    def test_non_matching_etag_is_rejected(self) -> None:
        self.assertFalse(function_app._etag_matches('"other"', '"expected"'))


if __name__ == "__main__":
    unittest.main()
