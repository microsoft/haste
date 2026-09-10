# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, patch

import azure.functions as func
from hastegeo.core.models.loading import (
    ActiveJob,
    ActiveJobIndicator,
    ActiveJobs,
)
from hastegeo.core.utils.async_cache import AsyncTTLCache

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-loading-route-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-loading-route-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
LAYER_ID = "123e4567-e89b-12d3-a456-426614174001"


def make_request(
    params: dict | None = None, headers: dict | None = None
) -> func.HttpRequest:
    return func.HttpRequest(
        method="GET",
        url="http://localhost/api/loading",
        headers=headers or {},
        params=params or {},
        route_params={},
        body=b"",
    )


def response_json(response: func.HttpResponse) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


class TestActiveJobsRoute(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cache = AsyncTTLCache(ttl_seconds=5, max_entries=1)
        self.cache_patcher = patch.object(
            function_app, "_active_jobs_cache", self.cache
        )
        self.cache_patcher.start()

    async def asyncTearDown(self) -> None:
        await self.cache.clear()
        self.cache_patcher.stop()

    def active_jobs(self) -> ActiveJobs:
        return ActiveJobs(
            jobs=[
                ActiveJob(
                    key="training-project-1-model-1",
                    kind="Training",
                    projectName="Project",
                    name="Model",
                    target="/project/project-1/layer-1",
                    indicator=ActiveJobIndicator(
                        id="ongoingTraining-project-1-model-1",
                        status="InProgress",
                        prefix="Training",
                        contextLabel="Model: Model - Training",
                    ),
                )
            ]
        )

    async def test_returns_etag_and_reuses_cached_representation(self) -> None:
        processor = AsyncMock()
        processor.load.return_value = self.active_jobs()
        authorize = AsyncMock(return_value=None)
        with patch.object(
            function_app, "_require_roles", new=authorize
        ), patch.object(
            function_app, "ActiveJobsProcessor", return_value=processor
        ) as processor_type:
            first = await function_app.GetActiveJobs(make_request())
            second = await function_app.GetActiveJobs(
                make_request(headers={"If-None-Match": first.headers["ETag"]})
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(response_json(first)["jobs"][0]["kind"], "Training")
        self.assertEqual(first.headers["X-Haste-Cache"], "MISS")
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.get_body(), b"")
        processor_type.assert_called_once_with(config=function_app.config)
        processor.load.assert_awaited_once_with()
        self.assertEqual(authorize.await_count, 2)
        for call in authorize.await_args_list:
            self.assertEqual(call.args[1], {"administrators", "contributors"})

    async def test_authorization_failure_skips_active_job_cache(self) -> None:
        forbidden = func.HttpResponse("Forbidden", status_code=403)
        with patch.object(
            function_app,
            "_require_roles",
            new=AsyncMock(return_value=forbidden),
        ), patch.object(function_app, "ActiveJobsProcessor") as processor_type:
            response = await function_app.GetActiveJobs(make_request())

        self.assertEqual(response.status_code, 403)
        processor_type.assert_not_called()

    async def test_missing_stats_returns_safe_not_found(self) -> None:
        processor = AsyncMock()
        processor.load.side_effect = FileNotFoundError("private path")
        with patch.object(
            function_app, "_require_roles", new=AsyncMock(return_value=None)
        ), patch.object(
            function_app, "ActiveJobsProcessor", return_value=processor
        ):
            response = await function_app.GetActiveJobs(make_request())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response_json(response)["error"]["code"], "NOT_FOUND")
        self.assertNotIn("private path", response.get_body().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
