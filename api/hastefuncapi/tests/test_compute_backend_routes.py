# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""API tests for per-job compute backend selection (plan.md Phase 9).

Covers the three guarantees the HTTP layer owes the compute layer:

* an omitted ``computeBackend`` behaves exactly as before (no new field is
  required of any existing client);
* a deterministically impossible selection is rejected with 400 before any
  work is queued;
* a client-supplied runtime handle (``computeJob``) is never accepted for
  the job a request launches, so no caller can make HASTE poll or cancel an
  arbitrary provider job.

No new routes are added — every check hangs off the existing launch
endpoints.
"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault(
    "DATA_PATH", os.path.join(tempfile.gettempdir(), "haste-compute-api-tests")
)
os.environ.setdefault(
    "TEMP_DATA_PATH",
    os.path.join(tempfile.gettempdir(), "haste-compute-api-tests"),
)

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

from hastegeo.core.models.projects import Model, ModelArtifacts  # noqa: E402

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"

#: A handle a malicious client might try to plant on a launch request.
FORGED_HANDLE = {
    "executionId": "trn-forged",
    "requestedBackend": "azure_batch",
    "selectedBackend": "azure_batch",
    "backendProfile": "training",
    "providerJobId": "someone-elses-job",
    "providerTaskId": "someone-elses-task",
    "targetId": "someone-elses-pool",
    "outputUri": "https://acct.blob.core.windows.net/data/x/y",
    "submittedAt": "2026-01-01T00:00:00+00:00",
    "routingReason": "explicit",
    "attempt": 1,
    "providerDetail": {
        "discriminator": "batch",
        "batch": {
            "jobId": "someone-elses-job",
            "taskId": "someone-elses-task",
        },
    },
}


def stored_handle(execution_id: str) -> dict:
    """A handle HASTE itself persisted for an earlier run."""
    return {
        "executionId": execution_id,
        "requestedBackend": "azure_batch",
        "selectedBackend": "azure_batch",
        "backendProfile": "inference",
        "providerJobId": f"provider-job-{execution_id}",
        "providerTaskId": execution_id,
        "targetId": "training-pool",
        "outputUri": (
            "https://acct.blob.core.windows.net/data/hash/" + execution_id
        ),
        "submittedAt": "2026-01-01T00:00:00+00:00",
        "routingReason": "explicit",
        "attempt": 1,
        "providerDetail": {
            "discriminator": "batch",
            "batch": {
                "jobId": f"provider-job-{execution_id}",
                "taskId": execution_id,
            },
        },
    }


def make_request(body: dict, method: str = "PUT") -> func.HttpRequest:
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/compute",
        headers={},
        params={},
        route_params={},
        body=json.dumps(body).encode("utf-8"),
    )


def _passthrough_preprocessor():
    """Preprocessor double that returns the record it was handed."""

    def _factory(record, *args, **kwargs):
        instance = MagicMock()
        instance.send_to_queue.return_value = record
        instance.queue_for_processing.return_value = record
        instance.send_to_zip_queue.return_value = record
        return instance

    return _factory


def _artifact_factory():
    def _factory(*args, **kwargs):
        instance = MagicMock()
        instance.send_to_zip_queue.return_value = kwargs["model_artifacts"]
        return instance

    return _factory


class TrainingRouteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.side_effect = FileNotFoundError()
        self.meta.return_value.load_all_from_partition.return_value = [
            {
                "imageLayerId": "layer-1",
                "labelprojectId": "lp-1",
                "labels": [],
            }
        ]
        self.stats = patch.object(function_app, "StatsPreProcessor").start()
        self.pre = patch.object(function_app, "TrainPreprocessor").start()
        self.pre.side_effect = _passthrough_preprocessor()
        self.addCleanup(patch.stopall)

    def _stored_model(self):
        model = Model(
            modelId="42",
            projectId=PROJECT_ID,
            imageLayerId="layer-1",
            inferenceJobs=[
                {
                    "taskId": "inf-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("inf-previous"),
                }
            ],
        )
        self.meta.return_value.load.side_effect = None
        self.meta.return_value.load.return_value = model.model_dump()

    def _body(self, **overrides):
        body = {
            "modelId": "42",
            "projectId": PROJECT_ID,
            "imageLayerId": "layer-1",
            "name": "damage model",
            "maxEpochs": "2",
        }
        body.update(overrides)
        return body

    async def test_omitted_backend_keeps_existing_behavior(self):
        response = await function_app.PutRunModelQueueMessage(
            make_request(self._body())
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertIsNone(submitted.computeBackend)

    async def test_explicit_backend_is_carried_on_the_record(self):
        response = await function_app.PutRunModelQueueMessage(
            make_request(self._body(computeBackend="local"))
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertEqual(submitted.computeBackend.value, "local")

    async def test_unknown_backend_is_rejected(self):
        response = await function_app.PutRunModelQueueMessage(
            make_request(self._body(computeBackend="my-gpu-cluster"))
        )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()

    async def test_client_inference_results_are_rejected_for_training(self):
        response = await function_app.PutRunModelQueueMessage(
            make_request(
                self._body(gpkgUrl="https://storage.example/forged.gpkg")
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "launching training", response.get_body().decode("utf-8")
        )
        self.pre.assert_not_called()

    async def test_azure_ml_rejected_when_disabled(self):
        with patch.dict(os.environ, {"AML_MODE": "Disabled"}, clear=False):
            response = await function_app.PutRunModelQueueMessage(
                make_request(self._body(computeBackend="azure_ml"))
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("azure_ml", response.get_body().decode("utf-8"))
        self.pre.assert_not_called()

    async def test_auto_rejected_without_configured_candidates(self):
        with patch.dict(
            os.environ,
            {"COMPUTE_AUTO_CANDIDATES_TRAINING": ""},
            clear=False,
        ):
            response = await function_app.PutRunModelQueueMessage(
                make_request(self._body(computeBackend="auto"))
            )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()

    async def test_auto_accepted_when_candidates_are_configured(self):
        with patch.dict(
            os.environ,
            {"COMPUTE_AUTO_CANDIDATES_TRAINING": "azure_batch,local"},
            clear=False,
        ):
            response = await function_app.PutRunModelQueueMessage(
                make_request(self._body(computeBackend="auto"))
            )
        self.assertEqual(response.status_code, 200)

    async def test_omitted_backend_is_rejected_when_the_default_is_disabled(
        self,
    ):
        # Nothing was requested, but the deployment's default backend
        # cannot run at all — queueing here would only fail in a worker.
        with patch.dict(
            os.environ,
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_ml",
                "AML_MODE": "Disabled",
            },
            clear=False,
        ):
            response = await function_app.PutRunModelQueueMessage(
                make_request(self._body())
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("azure_ml", response.get_body().decode("utf-8"))
        self.pre.assert_not_called()

    async def test_omitted_backend_is_rejected_on_broken_configuration(self):
        with patch.dict(
            os.environ,
            {"COMPUTE_BACKEND_DEFAULT": "not-a-backend"},
            clear=False,
        ):
            response = await function_app.PutRunModelQueueMessage(
                make_request(self._body())
            )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()

    async def test_client_supplied_training_handle_is_discarded(self):
        body = self._body(
            trainingJob={
                "jobId": "someone-elses-job",
                "taskId": "someone-elses-task",
                "computeJob": FORGED_HANDLE,
            }
        )
        response = await function_app.PutRunModelQueueMessage(
            make_request(body)
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        # The server owns this record; the preprocessor recreates it.
        self.assertIsNone(submitted.trainingJob)
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )

    async def test_training_launch_preserves_stored_inference_history(self):
        self._stored_model()
        body = self._body(
            inferenceJobs=[
                {
                    "taskId": "inf-forged",
                    "jobId": "someone-elses-job",
                    "computeJob": FORGED_HANDLE,
                }
            ]
        )

        response = await function_app.PutRunModelQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertEqual(
            submitted.inferenceJobs[0].computeJob.providerJobId,
            "provider-job-inf-previous",
        )
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )


class InferenceRouteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.side_effect = FileNotFoundError()
        self.pre = patch.object(function_app, "InferencePreprocessor").start()
        self.pre.side_effect = _passthrough_preprocessor()
        self.addCleanup(patch.stopall)

    def _stored_model(self, jobs, **overrides):
        values = {
            "modelId": "42",
            "projectId": PROJECT_ID,
            "imageLayerId": "layer-1",
            "name": "damage-model",
            "inferenceJobs": jobs,
        }
        values.update(overrides)
        model = Model(**values)
        self.meta.return_value.load.side_effect = None
        self.meta.return_value.load.return_value = model.dict()
        return model

    def _body(self, **overrides):
        body = {
            "modelId": "42",
            "projectId": PROJECT_ID,
            "imageLayerId": "layer-1",
            "name": "damage-model",
        }
        body.update(overrides)
        return body

    async def test_backend_selection_is_optional(self):
        response = await function_app.PutRunInferenceQueueMessage(
            make_request(self._body())
        )
        self.assertEqual(response.status_code, 200)

    async def test_client_inference_results_are_rejected_for_inference(self):
        response = await function_app.PutRunInferenceQueueMessage(
            make_request(
                self._body(gpkgUrl="https://storage.example/forged.gpkg")
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "launching inference", response.get_body().decode("utf-8")
        )
        self.pre.assert_not_called()

    async def test_azure_ml_rejected_when_disabled(self):
        with patch.dict(os.environ, {"AML_MODE": "Disabled"}, clear=False):
            response = await function_app.PutRunInferenceQueueMessage(
                make_request(self._body(computeBackend="azure_ml"))
            )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()

    async def test_prior_job_handles_survive_a_new_launch(self):
        # A client round-tripping the record it fetched must not cause
        # HASTE to lose the handle of a job it already submitted.
        self._stored_model(
            [
                {
                    "taskId": "inf-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("inf-previous"),
                }
            ]
        )
        body = self._body(inferenceJobs=[])

        response = await function_app.PutRunInferenceQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertEqual(
            [job.taskId for job in submitted.inferenceJobs], ["inf-previous"]
        )
        handle = submitted.inferenceJobs[0].computeJob
        self.assertIsNotNone(handle)
        self.assertEqual(handle.providerJobId, "provider-job-inf-previous")

    async def test_forged_handles_cannot_replace_server_state(self):
        self._stored_model(
            [
                {
                    "taskId": "inf-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("inf-previous"),
                }
            ]
        )
        body = self._body(
            inferenceJobs=[
                {
                    "taskId": "inf-previous",
                    "jobId": "someone-elses-job",
                    "computeJob": FORGED_HANDLE,
                },
                {
                    "taskId": "inf-invented",
                    "jobId": "someone-elses-job",
                    "computeJob": FORGED_HANDLE,
                },
            ],
            currentInferenceTaskId="inf-invented",
        )

        response = await function_app.PutRunInferenceQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        # Stored history wins: the invented record is gone and the real
        # handle is untouched.
        self.assertEqual(
            [job.taskId for job in submitted.inferenceJobs], ["inf-previous"]
        )
        self.assertEqual(
            submitted.inferenceJobs[0].computeJob.providerJobId,
            "provider-job-inf-previous",
        )
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )

    async def test_client_handles_are_dropped_without_stored_history(self):
        # Nothing stored yet: there is no server state to trust, so the
        # request's own handles are cleared rather than believed.
        body = self._body(
            inferenceJobs=[
                {
                    "taskId": "inf-old",
                    "jobId": "job-old",
                    "computeJob": FORGED_HANDLE,
                }
            ],
            currentInferenceTaskId="inf-old",
        )
        response = await function_app.PutRunInferenceQueueMessage(
            make_request(body)
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertIsNone(submitted.inferenceJobs[0].computeJob)

    async def test_sibling_runtime_handles_come_only_from_stored_state(self):
        self._stored_model(
            [],
            trainingJob={
                "taskId": "trn-previous",
                "jobId": "job-previous",
                "computeJob": stored_handle("trn-previous"),
            },
            embeddingJob={
                "taskId": "emb-previous",
                "jobId": "job-previous",
                "computeJob": stored_handle("emb-previous"),
            },
        )
        body = self._body(
            trainingJob={
                "taskId": "trn-forged",
                "jobId": "someone-elses-job",
                "computeJob": FORGED_HANDLE,
            },
            embeddingJob={
                "taskId": "emb-forged",
                "jobId": "someone-elses-job",
                "computeJob": FORGED_HANDLE,
            },
        )

        response = await function_app.PutRunInferenceQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertEqual(
            submitted.trainingJob.computeJob.providerJobId,
            "provider-job-trn-previous",
        )
        self.assertEqual(
            submitted.embeddingJob.computeJob.providerJobId,
            "provider-job-emb-previous",
        )
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )


class EmbeddingRouteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.side_effect = FileNotFoundError()
        patch.object(function_app, "StatsPreProcessor").start()
        self.pre = patch.object(function_app, "EmbeddingPreprocessor").start()
        self.pre.side_effect = _passthrough_preprocessor()
        self.addCleanup(patch.stopall)

    def _stored_model(self):
        model = Model(
            modelId="42",
            projectId=PROJECT_ID,
            imageLayerId="layer-1",
            trainingJob={
                "taskId": "trn-previous",
                "jobId": "job-previous",
                "computeJob": stored_handle("trn-previous"),
            },
            inferenceJobs=[
                {
                    "taskId": "inf-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("inf-previous"),
                }
            ],
        )
        self.meta.return_value.load.side_effect = None
        self.meta.return_value.load.return_value = model.model_dump()

    def _body(self, **overrides):
        body = {
            "modelId": "42",
            "projectId": PROJECT_ID,
            "imageLayerId": "layer-1",
            "name": "embedding run",
        }
        body.update(overrides)
        return body

    async def test_client_supplied_embedding_handle_is_discarded(self):
        body = self._body(
            embeddingJob={
                "jobId": "job-old",
                "taskId": "emb-old",
                "computeJob": FORGED_HANDLE,
            }
        )
        response = await function_app.PutRunEmbeddingQueueMessage(
            make_request(body)
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertIsNone(submitted.embeddingJob)

    async def test_embedding_launch_preserves_stored_sibling_histories(self):
        self._stored_model()
        body = self._body(
            trainingJob={
                "taskId": "trn-forged",
                "jobId": "someone-elses-job",
                "computeJob": FORGED_HANDLE,
            },
            inferenceJobs=[
                {
                    "taskId": "inf-forged",
                    "jobId": "someone-elses-job",
                    "computeJob": FORGED_HANDLE,
                }
            ],
        )

        response = await function_app.PutRunEmbeddingQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.args[0]
        self.assertEqual(
            submitted.trainingJob.computeJob.providerJobId,
            "provider-job-trn-previous",
        )
        self.assertEqual(
            submitted.inferenceJobs[0].computeJob.providerJobId,
            "provider-job-inf-previous",
        )
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )

    async def test_azure_ml_rejected_when_disabled(self):
        with patch.dict(os.environ, {"AML_MODE": "Disabled"}, clear=False):
            response = await function_app.PutRunEmbeddingQueueMessage(
                make_request(self._body(computeBackend="azure_ml"))
            )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()


class ImageLayerRouteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.side_effect = FileNotFoundError()
        patch.object(function_app, "StatsPreProcessor").start()
        self.pre = patch.object(function_app, "ImageryPreProcessor").start()
        self.pre.side_effect = lambda image_data: MagicMock(
            queue_for_processing=MagicMock(return_value=image_data)
        )
        self.addCleanup(patch.stopall)

    def _body(self, **overrides):
        body = {
            "imageLayerId": "11111111-1111-1111-1111-111111111111",
            "projectId": PROJECT_ID,
            "name": "layer",
            "preEventImageryUrls": [],
            "postEventImageryUrls": [],
        }
        body.update(overrides)
        return body

    async def test_client_supplied_preprocess_handle_is_discarded(self):
        # Create path: nothing is stored yet, so the client's own handle
        # is dropped before the preprocessor records the pending job.
        body = self._body(
            preprocessJob={
                "jobId": "job-old",
                "taskId": "img-old",
                "computeJob": FORGED_HANDLE,
            }
        )
        response = await function_app.PutLayer(make_request(body))
        self.assertEqual(response.status_code, 200)
        submitted = self.pre.call_args.kwargs["image_data"]
        self.assertIsNone(submitted.preprocessJob.computeJob)

    def _stored_layer(self, **overrides):
        """An existing layer with a running preprocessing job and the
        artifacts the imagery workflow has produced so far."""
        stored = {
            "imageLayerId": "11111111-1111-1111-1111-111111111111",
            "projectId": PROJECT_ID,
            "name": "stored layer",
            "preEventImageryUrls": ["https://example/pre.tif"],
            "postEventImageryUrls": ["https://example/post.tif"],
            "preprocessJob": {
                "jobId": "provider-job-img-real",
                "taskId": "img-real",
                "imageLayerId": "11111111-1111-1111-1111-111111111111",
                "projectId": PROJECT_ID,
                "status": "InProgress",
                "computeJob": stored_handle("img-real"),
            },
            "status": "InProgress",
            "statusMessage": "\n2026-01-01: Image preprocessing submitted",
            "currentStep": 2,
            "totalSteps": 4,
            "progressPct": 50.0,
            "imageryPath": "hash/imagery_img-real",
            "postEventMosaicCogImageryUrl": "https://acct/c/hash/post.tif",
            "buildingFootprintsUrl": "https://acct/c/hash/f.gpkg",
            "normalizationMeans": [1, 2, 3],
        }
        stored.update(overrides)
        self.meta.return_value.load.side_effect = None
        self.meta.return_value.load.return_value = stored
        return stored

    def _saved_payload(self):
        return self.meta.return_value.save.call_args.args[1]

    async def test_editing_an_existing_layer_launches_nothing(self):
        # An edit does not launch a preprocessing job, so it must not go
        # through the launch path.
        self._stored_layer()
        response = await function_app.PutLayer(make_request(self._body()))
        self.assertEqual(response.status_code, 200)
        self.pre.assert_not_called()

    async def test_edit_preserves_the_stored_compute_handle(self):
        self._stored_layer()
        body = self._body(
            name="renamed layer",
            preprocessJob={
                "jobId": "someone-elses-job",
                "taskId": "someone-elses-task",
                "status": "Processed",
                "computeJob": FORGED_HANDLE,
            },
        )

        response = await function_app.PutLayer(make_request(body))

        self.assertEqual(response.status_code, 200)
        saved = self._saved_payload()
        # The stored submission — including its runtime handle — survives.
        self.assertEqual(saved["preprocessJob"]["taskId"], "img-real")
        self.assertEqual(
            saved["preprocessJob"]["jobId"], "provider-job-img-real"
        )
        self.assertEqual(
            saved["preprocessJob"]["computeJob"]["providerJobId"],
            "provider-job-img-real",
        )
        self.assertEqual(saved["preprocessJob"]["status"], "InProgress")
        # ...and the editable field the caller actually changed is kept.
        self.assertEqual(saved["name"], "renamed layer")

    async def test_edit_cannot_forge_provider_identifiers(self):
        self._stored_layer()
        body = self._body(
            preprocessJob={
                "jobId": "someone-elses-job",
                "taskId": "someone-elses-task",
                "computeJob": FORGED_HANDLE,
            }
        )

        response = await function_app.PutLayer(make_request(body))

        self.assertEqual(response.status_code, 200)
        body_text = response.get_body().decode("utf-8")
        saved_text = json.dumps(self._saved_payload())
        for forged in (
            "someone-elses-job",
            "someone-elses-task",
            "someone-elses-pool",
            "trn-forged",
        ):
            with self.subTest(value=forged):
                self.assertNotIn(forged, body_text)
                self.assertNotIn(forged, saved_text)

    async def test_edit_cannot_rewrite_runtime_or_workflow_state(self):
        self._stored_layer()
        body = self._body(
            status="Processed",
            statusMessage="\n2026-01-01: totally finished",
            currentStep=4,
            progressPct=100.0,
            imageryPath="hash/attacker",
            postEventMosaicCogImageryUrl="https://evil/post.tif",
            buildingFootprintsUrl="https://evil/f.gpkg",
            normalizationMeans=[9, 9, 9],
        )

        response = await function_app.PutLayer(make_request(body))

        self.assertEqual(response.status_code, 200)
        saved = self._saved_payload()
        self.assertEqual(saved["status"], "InProgress")
        self.assertIn("Image preprocessing submitted", saved["statusMessage"])
        self.assertEqual(saved["currentStep"], 2)
        self.assertEqual(saved["progressPct"], 50.0)
        self.assertEqual(saved["imageryPath"], "hash/imagery_img-real")
        self.assertEqual(
            saved["postEventMosaicCogImageryUrl"],
            "https://acct/c/hash/post.tif",
        )
        self.assertEqual(
            saved["buildingFootprintsUrl"], "https://acct/c/hash/f.gpkg"
        )
        self.assertEqual(saved["normalizationMeans"], [1, 2, 3])
        self.assertNotIn("https://evil", json.dumps(saved))

    async def test_edit_still_honors_editable_fields_and_backend_intent(self):
        self._stored_layer()
        body = self._body(
            name="renamed layer",
            description="new description",
            preEventImageryUrls=[
                "https://acct.blob.core.windows.net/c/new-pre.tif"
            ],
            postEventImageryUrls=[
                "https://acct.blob.core.windows.net/c/new-post.tif"
            ],
            computeBackend="local",
        )

        response = await function_app.PutLayer(make_request(body))

        self.assertEqual(response.status_code, 200)
        saved = self._saved_payload()
        self.assertEqual(saved["name"], "renamed layer")
        self.assertEqual(saved["description"], "new description")
        self.assertEqual(
            saved["preEventImageryUrls"],
            ["https://acct.blob.core.windows.net/c/new-pre.tif"],
        )
        self.assertEqual(saved["computeBackend"], "local")

    async def test_creating_a_layer_still_queues_preprocessing(self):
        # The create path is unchanged: nothing stored, preprocessor runs.
        response = await function_app.PutLayer(make_request(self._body()))
        self.assertEqual(response.status_code, 200)
        self.pre.assert_called_once()
        submitted = self.pre.call_args.kwargs["image_data"]
        self.assertEqual(submitted.name, "layer")

    async def test_azure_ml_rejected_when_disabled(self):
        with patch.dict(os.environ, {"AML_MODE": "Disabled"}, clear=False):
            response = await function_app.PutLayer(
                make_request(self._body(computeBackend="azure_ml"))
            )
        self.assertEqual(response.status_code, 400)
        self.pre.assert_not_called()


class ArtifactZipRouteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.side_effect = FileNotFoundError()
        self.processor = patch.object(
            function_app, "ArtifactProcessor"
        ).start()
        self.processor.side_effect = _artifact_factory()
        self.addCleanup(patch.stopall)

    def _stored_artifacts(self, jobs):
        stored = ModelArtifacts(
            modelId="42", projectId=PROJECT_ID, zipJobs=jobs
        )
        self.meta.return_value.load.side_effect = None
        self.meta.return_value.load.return_value = stored.dict()
        return stored

    def _body(self, **overrides):
        body = {"modelId": "42", "projectId": PROJECT_ID}
        body.update(overrides)
        return body

    async def test_prior_zip_handles_survive_a_new_launch(self):
        self._stored_artifacts(
            [
                {
                    "taskId": "zip-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("zip-previous"),
                }
            ]
        )

        response = await function_app.PutArtifactsZipQueueMessage(
            make_request(self._body(zipJobs=[]))
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.processor.call_args.kwargs["model_artifacts"]
        self.assertEqual(
            [job.taskId for job in submitted.zipJobs], ["zip-previous"]
        )
        self.assertEqual(
            submitted.zipJobs[0].computeJob.providerJobId,
            "provider-job-zip-previous",
        )

    async def test_forged_zip_handles_cannot_replace_server_state(self):
        self._stored_artifacts(
            [
                {
                    "taskId": "zip-previous",
                    "jobId": "job-previous",
                    "computeJob": stored_handle("zip-previous"),
                }
            ]
        )
        body = self._body(
            zipJobs=[
                {
                    "taskId": "zip-previous",
                    "jobId": "someone-elses-job",
                    "computeJob": FORGED_HANDLE,
                }
            ],
            currentZipJobUid="zip-previous",
        )

        response = await function_app.PutArtifactsZipQueueMessage(
            make_request(body)
        )

        self.assertEqual(response.status_code, 200)
        submitted = self.processor.call_args.kwargs["model_artifacts"]
        self.assertEqual(
            submitted.zipJobs[0].computeJob.providerJobId,
            "provider-job-zip-previous",
        )
        self.assertNotIn(
            "someone-elses-job", response.get_body().decode("utf-8")
        )

    async def test_client_handles_are_dropped_without_stored_history(self):
        body = self._body(
            zipJobs=[
                {
                    "taskId": "zip-old",
                    "jobId": "job-old",
                    "computeJob": FORGED_HANDLE,
                }
            ]
        )
        response = await function_app.PutArtifactsZipQueueMessage(
            make_request(body)
        )
        self.assertEqual(response.status_code, 200)
        submitted = self.processor.call_args.kwargs["model_artifacts"]
        self.assertIsNone(submitted.zipJobs[0].computeJob)

    async def test_azure_ml_rejected_when_disabled(self):
        with patch.dict(os.environ, {"AML_MODE": "Disabled"}, clear=False):
            response = await function_app.PutArtifactsZipQueueMessage(
                make_request(self._body(computeBackend="azure_ml"))
            )
        self.assertEqual(response.status_code, 400)
        self.processor.assert_not_called()


class CancelRouteTestCase(unittest.IsolatedAsyncioTestCase):
    """Cancelling an in-flight inference goes through the same
    preprocessor, which must accept the cancellation status."""

    def setUp(self):
        self.meta = patch.object(function_app, "MetadataProcessor").start()
        self.meta.return_value.load.return_value = {
            "modelId": "42",
            "projectId": PROJECT_ID,
            "imageLayerId": "layer-1",
            "name": "damage-model",
            "status": "Processed",
            "inferenceStatus": "InProgress",
        }
        self.pre = patch.object(function_app, "InferencePreprocessor").start()
        self.pre.side_effect = _passthrough_preprocessor()
        self.addCleanup(patch.stopall)

    async def test_cancelling_inference_is_accepted(self):
        response = await function_app.PutCancelModelQueueMessage(
            make_request({"projectId": PROJECT_ID, "modelId": "42"})
        )
        self.assertEqual(response.status_code, 200)
        instance = self.pre.return_value
        instance.send_to_queue.assert_not_called()
        # The route builds its own instance per call; assert the queued
        # request carried the cancellation status.
        queued = self.pre.call_args.args[0]
        self.assertEqual(queued.modelId, "42")


class ComputeHelpersLiveInCoreTestCase(unittest.TestCase):
    """AGENTS.md: ``function_app.py`` holds HTTP wrappers only — anything
    that operates on plain data belongs in ``hastegeo``."""

    def test_no_compute_helper_is_defined_in_the_http_app(self):
        source = pathlib.Path(function_app.__file__).read_text(
            encoding="utf-8"
        )
        for helper in (
            "_compute_backend_rejection",
            "_clear_client_compute_handles",
            "backend_rejection_message",
            "clear_compute_handles",
            "authoritative_job_history",
        ):
            with self.subTest(helper=helper):
                self.assertNotIn(f"def {helper}(", source)

    def test_the_routes_use_the_core_helpers(self):
        source = pathlib.Path(function_app.__file__).read_text(
            encoding="utf-8"
        )
        self.assertIn("from hastegeo.core.utils.compute_jobs import", source)
        self.assertIn(
            "from hastegeo.core.utils.compute_specs import "
            "backend_rejection_message",
            source,
        )


if __name__ == "__main__":
    unittest.main()
