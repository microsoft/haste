import asyncio
import base64
import io
import json
import os
import unittest
import uuid
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, Mock, patch

import azure.functions as func
from hastegeo.core.utils.async_cache import AsyncTTLCache

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("PUBLISHING_ENABLED", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-publishing-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-publishing-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

from hastegeo.core.models.publishing import (  # noqa: E402
    PublishDatasetOptions,
    PublishedDataset,
)
from hastegeo.core.processors.publishing import (  # noqa: E402
    PublishingDependencyError,
    PublishingDisabledError,
    PublishingPermissionError,
    PublishingStateConflictError,
)
from hastegeo.core.publishing.repository import (  # noqa: E402
    PublishedDatasetsExistError,
)

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
DATASET_ID = "3e8d5e90-f2fc-5412-9f97-a52c07815f0b"
REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"


def make_request(
    method: str = "GET",
    params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> func.HttpRequest:
    encoded_body = (
        json.dumps(body).encode("utf-8") if body is not None else b""
    )
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/publishing",
        headers=headers or {},
        params=params or {},
        route_params={},
        body=encoded_body,
    )


def response_json(response: func.HttpResponse) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


def make_dataset(status: str = "PENDING") -> PublishedDataset:
    return PublishedDataset(
        datasetId=DATASET_ID,
        requestId=REQUEST_ID,
        requestFingerprint="a" * 64,
        name="Published damage assessment",
        projectId=PROJECT_ID,
        imageLayerId="layer-1",
        modelId="42",
        target="local",
        status=status,
        publishedByUser="publisher-object-id",
        createdDate="2026-08-06T00:00:00Z",
        updatedDate="2026-08-06T00:00:00Z",
    )


class TestPublishingRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.catalog_cache = AsyncTTLCache(ttl_seconds=5, max_entries=16)
        self.cache_patcher = patch.object(
            function_app,
            "_published_datasets_cache",
            self.catalog_cache,
        )
        self.cache_patcher.start()

    async def asyncTearDown(self) -> None:
        await self.catalog_cache.clear()
        self.cache_patcher.stop()

    async def test_inference_launch_rejects_client_runtime_state(self) -> None:
        response = await function_app.PutRunInferenceQueueMessage(
            make_request(
                method="PUT",
                body={
                    "projectId": PROJECT_ID,
                    "modelId": "42",
                    "gpkgUrl": "https://storage.example/forged.gpkg",
                },
            )
        )

        self.assertEqual(response.status_code, 400)

    async def test_layer_request_rejects_workflow_owned_artifact_paths(
        self,
    ) -> None:
        response = await function_app.PutLayer(
            make_request(
                method="PUT",
                body={
                    "projectId": PROJECT_ID,
                    "name": "New layer",
                    "postEventProcessedImageryUrl": (
                        "https://attacker.example/admin.tif"
                    ),
                    "buildingFootprintsUrl": (
                        "https://attacker.example/users_acl.json"
                    ),
                    "status": "Processed",
                },
            )
        )

        self.assertEqual(response.status_code, 400)

    async def test_trusted_principal_maps_to_active_haste_user(self) -> None:
        principal = {
            "userId": "OBJECT-ID",
            "userDetails": "publisher@example.com",
            "userRoles": ["authenticated", "contributors"],
        }
        encoded = base64.b64encode(
            json.dumps(principal).encode("utf-8")
        ).decode("ascii")
        metadata = Mock()
        metadata.load.return_value = [
            {
                "userId": "publisher@example.com",
                "objectId": "OBJECT-ID",
                "userRoles": ["contributors"],
                "status": function_app.config.get_user_statuses().ACTIVE.value,
                "deleted": False,
            }
        ]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            caller, error = await function_app._get_active_publishing_caller(
                make_request(headers={"x-ms-client-principal": encoded})
            )

        self.assertIsNone(error)
        self.assertEqual(caller["id"], "object-id")
        self.assertEqual(caller["roles"], {"contributors"})

    async def test_publishing_roles_use_principal_acl_intersection(
        self,
    ) -> None:
        principal = {
            "userId": "OBJECT-ID",
            "userDetails": "publisher@example.com",
            "userRoles": ["authenticated", "administrators"],
        }
        encoded = base64.b64encode(
            json.dumps(principal).encode("utf-8")
        ).decode("ascii")
        metadata = Mock()
        metadata.load.return_value = [
            {
                "userId": "publisher@example.com",
                "objectId": "OBJECT-ID",
                "userRoles": ["contributors"],
                "status": function_app.config.get_user_statuses().ACTIVE.value,
                "deleted": False,
            }
        ]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            caller, error = await function_app._get_active_publishing_caller(
                make_request(headers={"x-ms-client-principal": encoded})
            )

        self.assertIsNone(caller)
        self.assertEqual(error.status_code, 403)
        self.assertEqual(response_json(error)["error"]["code"], "FORBIDDEN")

    async def test_invalid_principal_header_is_unauthenticated(self) -> None:
        with patch.object(function_app, "DEVELOPMENT_MODE", False):
            caller, error = await function_app._get_active_publishing_caller(
                make_request(
                    headers={"x-ms-client-principal": "not-valid-base64"}
                )
            )

        self.assertIsNone(caller)
        self.assertEqual(error.status_code, 401)

    async def test_provider_list_allows_active_viewer(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.dict(
            function_app.config.publishing_config,
            {"publishing_enabled": True},
        ):
            response = await function_app.GetPublishingProviders(
                make_request()
            )

        payload = response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["publishingEnabled"])
        self.assertEqual(payload["providers"][0]["id"], "local")

    async def test_options_reject_viewer_without_mutation_role(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ):
            response = await function_app.GetPublishDatasetOptions(
                make_request(
                    params={
                        "projectId": PROJECT_ID,
                        "imageLayerId": str(uuid.uuid4()),
                        "modelId": "42",
                    }
                )
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response_json(response)["error"]["code"], "FORBIDDEN")

    async def test_options_return_server_verified_artifacts(self) -> None:
        caller = {"id": "contributor", "roles": {"contributors"}}
        options = PublishDatasetOptions(
            projectId=PROJECT_ID,
            projectName="Project",
            imageLayerId=str(uuid.uuid4()),
            imageLayerName="Layer",
            modelId="42",
            modelName="Model",
            defaultName="Project - Layer",
            availableArtifacts=[
                {
                    "kind": "gpkg",
                    "sourcePath": "damage.gpkg",
                    "mediaType": "application/geopackage+sqlite3",
                    "sizeBytes": 10,
                    "sourceEtag": "etag-1",
                }
            ],
        )
        resolver = Mock()
        resolver.resolve_options.return_value = options
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "PublishingSourceResolver",
            return_value=resolver,
        ):
            response = await function_app.GetPublishDatasetOptions(
                make_request(
                    params={
                        "projectId": PROJECT_ID,
                        "imageLayerId": str(options.imageLayerId),
                        "modelId": "42",
                    }
                )
            )

        self.assertEqual(response.status_code, 200)
        payload = response_json(response)["publishDatasetOptions"]
        self.assertEqual(payload["availableArtifacts"][0]["kind"], "gpkg")

    async def test_catalog_returns_bounded_pagination_metadata(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        repository = Mock()
        repository.list_page.return_value = ([make_dataset("PUBLISHED")], 45)
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            response = await function_app.GetPublishedDatasets(
                make_request(
                    params={
                        "page": "2",
                        "pageSize": "20",
                        "target": "local",
                        "search": "damage",
                        "sortKey": "name",
                        "sortDirection": "asc",
                    }
                )
            )

        payload = response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["pagination"],
            {"page": 2, "pageSize": 20, "totalCount": 45},
        )
        repository.list_page.assert_called_once_with(
            page=2,
            page_size=20,
            project_id=None,
            target=function_app.PublishTarget.LOCAL,
            status=None,
            search="damage",
            sort_key="name",
            sort_direction="asc",
        )

    async def test_catalog_reuses_same_query_after_authorization(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        authorize = AsyncMock(return_value=(caller, None))
        repository = Mock()
        repository.list_page.return_value = ([make_dataset("PUBLISHED")], 1)
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=authorize,
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            first = await function_app.GetPublishedDatasets(make_request())
            second = await function_app.GetPublishedDatasets(make_request())

        self.assertEqual(first.headers["X-Haste-Cache"], "MISS")
        self.assertEqual(second.headers["X-Haste-Cache"], "HIT")
        self.assertEqual(authorize.await_count, 2)
        repository.list_page.assert_called_once()

    async def test_catalog_concurrent_requests_share_one_read(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        repository = Mock()
        repository.list_page.return_value = ([make_dataset("PUBLISHED")], 1)
        started = asyncio.Event()
        release = asyncio.Event()
        thread_calls = 0

        async def fake_to_thread(function, *args, **kwargs):
            nonlocal thread_calls
            thread_calls += 1
            started.set()
            await release.wait()
            return function(*args, **kwargs)

        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ), patch.object(
            function_app.asyncio,
            "to_thread",
            new=fake_to_thread,
        ):
            first = asyncio.create_task(
                function_app.GetPublishedDatasets(make_request())
            )
            await started.wait()
            second = asyncio.create_task(
                function_app.GetPublishedDatasets(make_request())
            )
            await asyncio.sleep(0)
            release.set()
            responses = await asyncio.gather(first, second)

        self.assertEqual(thread_calls, 1)
        repository.list_page.assert_called_once()
        self.assertEqual(
            {response.headers["X-Haste-Cache"] for response in responses},
            {"MISS", "HIT"},
        )

    async def test_catalog_matching_etag_returns_empty_304(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        repository = Mock()
        repository.list_page.return_value = ([make_dataset("PUBLISHED")], 1)
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            first = await function_app.GetPublishedDatasets(make_request())
            response = await function_app.GetPublishedDatasets(
                make_request(headers={"If-None-Match": first.headers["ETag"]})
            )

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.get_body(), b"")
        self.assertEqual(response.headers["X-Haste-Cache"], "HIT")
        repository.list_page.assert_called_once()

    async def test_catalog_query_fields_use_separate_cache_entries(
        self,
    ) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        repository = Mock()
        repository.list_page.return_value = ([], 0)
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            await function_app.GetPublishedDatasets(make_request())
            await function_app.GetPublishedDatasets(
                make_request(params={"status": "PUBLISHED"})
            )

        self.assertEqual(repository.list_page.call_count, 2)

    async def test_catalog_no_cache_refreshes_response(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        repository = Mock()
        repository.list_page.side_effect = [
            ([make_dataset("PENDING")], 1),
            ([make_dataset("PUBLISHED")], 1),
        ]
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            await function_app.GetPublishedDatasets(make_request())
            response = await function_app.GetPublishedDatasets(
                make_request(headers={"Cache-Control": "no-cache"})
            )

        self.assertEqual(response.headers["X-Haste-Cache"], "MISS")
        self.assertEqual(
            response_json(response)["publishedDatasets"][0]["status"],
            "PUBLISHED",
        )
        self.assertEqual(repository.list_page.call_count, 2)

    async def test_successful_mutation_invalidates_catalog_cache(self) -> None:
        caller = {"id": "publisher-object-id", "roles": {"contributors"}}
        repository = Mock()
        repository.list_page.side_effect = [
            ([make_dataset("PENDING")], 1),
            ([make_dataset("PUBLISHED")], 1),
        ]
        processor = Mock()
        processor.update_metadata.return_value = make_dataset("PUBLISHED")
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "PublishingRepository", return_value=repository
        ), patch.object(
            function_app, "_publishing_processor", return_value=processor
        ):
            first = await function_app.GetPublishedDatasets(make_request())
            mutation = await function_app.PutUpdatePublishedDataset(
                make_request(
                    method="PUT",
                    body={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                        "name": "Updated dataset",
                    },
                )
            )
            second = await function_app.GetPublishedDatasets(make_request())

        self.assertEqual(first.headers["X-Haste-Cache"], "MISS")
        self.assertEqual(mutation.status_code, 200)
        self.assertEqual(second.headers["X-Haste-Cache"], "MISS")
        self.assertEqual(
            response_json(second)["publishedDatasets"][0]["status"],
            "PUBLISHED",
        )
        self.assertEqual(repository.list_page.call_count, 2)

    async def test_catalog_rejects_unbounded_page_size(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ):
            response = await function_app.GetPublishedDatasets(
                make_request(params={"pageSize": "101"})
            )

        self.assertEqual(response.status_code, 400)

    async def test_catalog_rejects_one_character_search(self) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ):
            response = await function_app.GetPublishedDatasets(
                make_request(params={"search": "a"})
            )

        self.assertEqual(response.status_code, 400)

    async def test_publish_uses_trusted_caller_identity(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        processor = Mock()
        prepared = Mock(existing=None)
        processor.prepare_create.return_value = prepared
        processor.create_prepared.return_value = make_dataset()
        assessment = Mock()
        assessment.generate = AsyncMock(return_value={"predictedDamaged": 5})
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ), patch.object(
            function_app,
            "AssessmentReportProcessor",
            return_value=assessment,
        ):
            response = await function_app.PutPublishDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "requestId": REQUEST_ID,
                        "projectId": PROJECT_ID,
                        "imageLayerId": "layer-1",
                        "modelId": "42",
                        "name": "Published damage assessment",
                        "target": "local",
                        "artifacts": ["gpkg"],
                    },
                )
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            processor.prepare_create.call_args.args[1], caller["id"]
        )
        self.assertEqual(
            processor.create_prepared.call_args.args,
            (prepared, {"predictedDamaged": 5}),
        )
        assessment.generate.assert_awaited_once_with(
            PROJECT_ID,
            "layer-1",
            "42",
            max_total_bytes=function_app._PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES,
        )

    async def test_publish_replay_skips_assessment_generation(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        processor = Mock()
        processor.prepare_create.return_value = Mock(
            existing=make_dataset("PUBLISHED")
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ), patch.object(
            function_app, "AssessmentReportProcessor"
        ) as assessment_type:
            response = await function_app.PutPublishDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "requestId": REQUEST_ID,
                        "projectId": PROJECT_ID,
                        "imageLayerId": "layer-1",
                        "modelId": "42",
                        "name": "Published damage assessment",
                        "target": "local",
                        "artifacts": ["gpkg"],
                    },
                )
            )

        self.assertEqual(response.status_code, 202)
        assessment_type.assert_not_called()
        processor.create_prepared.assert_not_called()

    async def test_disabled_publish_stops_before_assessment(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        processor = Mock()
        processor.prepare_create.side_effect = PublishingDisabledError(
            "Publishing is disabled"
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ), patch.object(
            function_app, "AssessmentReportProcessor"
        ) as assessment_type:
            response = await function_app.PutPublishDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "requestId": REQUEST_ID,
                        "projectId": PROJECT_ID,
                        "imageLayerId": "layer-1",
                        "modelId": "42",
                        "name": "Published damage assessment",
                        "target": "local",
                        "artifacts": ["gpkg"],
                    },
                )
            )

        self.assertEqual(response.status_code, 503)
        assessment_type.assert_not_called()

    async def test_publish_rejects_forged_body_identity(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ):
            response = await function_app.PutPublishDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "requestId": REQUEST_ID,
                        "projectId": PROJECT_ID,
                        "imageLayerId": "layer-1",
                        "modelId": "42",
                        "name": "Published damage assessment",
                        "target": "local",
                        "artifacts": ["gpkg"],
                        "publishedByUser": "attacker",
                    },
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response_json(response)["error"]["code"], "VALIDATION_ERROR"
        )

    async def test_retry_returns_structured_disabled_response(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        processor = Mock()
        processor.retry.side_effect = PublishingDisabledError(
            "Publishing is disabled"
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.PutRetryPublishedDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    },
                )
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response_json(response)["error"]["code"],
            "PUBLISHING_UNAVAILABLE",
        )

    async def test_retry_returns_structured_dependency_response(self) -> None:
        caller = {
            "id": "publisher-object-id",
            "roles": {"contributors"},
        }
        processor = Mock()
        processor.retry.side_effect = PublishingDependencyError(
            "Unable to enqueue publishing retry"
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.PutRetryPublishedDatasetQueueMessage(
                make_request(
                    method="PUT",
                    body={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    },
                )
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response_json(response)["error"]["code"],
            "PUBLISHING_UNAVAILABLE",
        )

    async def test_unpublish_returns_structured_permission_response(
        self,
    ) -> None:
        caller = {"id": "other-user", "roles": {"contributors"}}
        processor = Mock()
        processor.request_unpublish.side_effect = PublishingPermissionError(
            "Only the publisher may unpublish"
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.DeletePublishedDataset(
                make_request(
                    method="DELETE",
                    params={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    },
                )
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response_json(response)["error"]["code"], "FORBIDDEN")

    async def test_force_remove_returns_removed_record(self) -> None:
        caller = {"id": "publisher-object-id", "roles": {"contributors"}}
        processor = Mock()
        processor.force_remove.return_value = make_dataset("UNPUBLISH_FAILED")
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.ForceRemovePublishedDataset(
                make_request(
                    method="DELETE",
                    params={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    },
                )
            )

        self.assertEqual(response.status_code, 200)
        processor.force_remove.assert_called_once_with(
            PROJECT_ID, DATASET_ID, "publisher-object-id", False
        )
        self.assertEqual(
            response_json(response)["publishedDataset"]["datasetId"],
            DATASET_ID,
        )

    async def test_force_remove_returns_structured_state_conflict(
        self,
    ) -> None:
        caller = {"id": "publisher-object-id", "roles": {"contributors"}}
        processor = Mock()
        processor.force_remove.side_effect = PublishingStateConflictError(
            "Force-remove is only allowed for a dataset stuck in a failed "
            "state, not PUBLISHED"
        )
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.ForceRemovePublishedDataset(
                make_request(
                    method="DELETE",
                    params={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    },
                )
            )

        self.assertEqual(response.status_code, 409)

    async def test_detail_returns_fresh_urls_separate_from_metadata(
        self,
    ) -> None:
        caller = {"id": "viewer", "roles": {"authenticated"}}
        processor = Mock()
        processor.get_dataset.return_value = make_dataset("PUBLISHED")
        processor.get_download_urls.return_value = {
            "gpkg": "https://storage/blob.gpkg?short-lived"
        }
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app,
            "_publishing_processor",
            return_value=processor,
        ):
            response = await function_app.GetPublishedDataset(
                make_request(
                    params={
                        "projectId": PROJECT_ID,
                        "datasetId": DATASET_ID,
                    }
                )
            )

        payload = response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["downloadUrls"]["gpkg"],
            "https://storage/blob.gpkg?short-lived",
        )
        self.assertNotIn("downloadUrls", payload["publishedDataset"])

    async def test_project_delete_conflicts_when_publications_exist(
        self,
    ) -> None:
        repository = Mock()
        repository.delete_project_if_unpublished.side_effect = (
            PublishedDatasetsExistError("Unpublish datasets first")
        )
        with patch.object(
            function_app, "PublishingRepository", return_value=repository
        ):
            response = await function_app.DeleteProject(
                make_request(method="DELETE", params={"projectId": PROJECT_ID})
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response_json(response)["error"]["code"],
            "PUBLISHED_DATASETS_EXIST",
        )

    async def test_update_route_applies_only_supplied_fields(self) -> None:
        caller = {"id": "publisher-object-id", "roles": {"contributors"}}
        processor = Mock()
        processor.update_metadata.return_value = make_dataset("PUBLISHED")
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ), patch.object(
            function_app, "_publishing_processor", return_value=processor
        ):
            response = await function_app.PutUpdatePublishedDataset(
                make_request(
                    method="PUT",
                    body={
                        "projectId": str(PROJECT_ID),
                        "datasetId": str(DATASET_ID),
                        "interactiveViewerUrl": "https://viewer.example.com/x",
                    },
                )
            )

        self.assertEqual(response.status_code, 200)
        args = processor.update_metadata.call_args.args
        self.assertEqual(
            args[4],
            {"interactiveViewerUrl": "https://viewer.example.com/x"},
        )

    async def test_update_route_rejects_non_https_viewer(self) -> None:
        caller = {"id": "publisher-object-id", "roles": {"contributors"}}
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(return_value=(caller, None)),
        ):
            response = await function_app.PutUpdatePublishedDataset(
                make_request(
                    method="PUT",
                    body={
                        "projectId": str(PROJECT_ID),
                        "datasetId": str(DATASET_ID),
                        "interactiveViewerUrl": "http://insecure.example",
                    },
                )
            )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
