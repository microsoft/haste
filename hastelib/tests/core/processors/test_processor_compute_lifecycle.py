# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Lifecycle tests for the migrated workload processors.

Covers, per workload: the stable pre-queue task id and its reuse (so a
duplicate queue delivery cannot mint a second provider job), handle
persistence alongside the legacy ``jobId``/``taskId``, legacy-record
fallback, status mapping onto the unchanged HASTE status strings, output
and log reads, cancellation, and automatic follow-on backend inheritance.

Every test injects a ``ComputeExecutionService`` backed by an in-memory
fake adapter — no provider SDK is contacted.

See spec/features/aml-compute-backend/plan.md Phases 8-9.
"""

import json
import unittest
from fnmatch import fnmatch
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    BatchProviderDetail,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeWorkload,
    LocalProviderDetail,
    OutputPersistenceMode,
)
from hastegeo.core.models.projects import (
    ImageLayer,
    ImageryPreprocessJob,
    InferenceJob,
    Model,
    ModelArtifacts,
    TrainingJob,
    ZipJob,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.runners.execution_service import ComputeExecutionService
from hastegeo.core.runners.registry import RunnerRegistry
from hastegeo.core.utils.compute_specs import compute_profile, output_prefix
from hastegeo.core.utils.metadata import MetadataUtils

PROJECT_ID = "proj-1"
PROJECT_HASH = MetadataUtils.hash_string(PROJECT_ID)
CONTAINER_URL = "https://acct.blob.core.windows.net/data"
STATUS = Config().get_status_types()

_PROFILES = [compute_profile(w) for w in ComputeWorkload] + ["default"]

#: Provider-detail slot each backend's handle must populate.
_PROVIDER_DISCRIMINATOR = {
    ComputeBackend.AZURE_BATCH: "batch",
    ComputeBackend.AZURE_ML: "azure_ml",
    ComputeBackend.LOCAL: "local",
}


class RecordingRunner(ComputeRunner):
    """Self-contained in-memory ``ComputeRunner`` for these tests.

    Deliberately defined here rather than imported from another test
    module: ``tests`` is not an importable package during a clean
    collection, so a cross-test import breaks the suite depending on how
    pytest is invoked.

    Records every call, returns an idempotent handle per ``executionId``
    (a second ``submit`` for the same id reuses the first handle, like a
    real adapter's get-or-create), and lets a test drive the reported
    state and the contents ``read_output`` returns.
    """

    def __init__(self, config=None, backend=ComputeBackend.AZURE_BATCH):
        # No Config() construction: these tests must not depend on any
        # storage/provider configuration being present.
        self.config = config
        self.backend = backend
        self.calls = []
        self.jobs = {}
        self.specs = []
        self.handles = []
        self.state = ComputeJobState.RUNNING
        self.outputs = {}
        self.capacity_state = CapacityState.AVAILABLE

    def validate(self, spec):
        self.calls.append(("validate", spec.executionId))

    def submit(self, spec):
        self.calls.append(("submit", spec.executionId))
        self.specs.append(spec)
        existing = self.jobs.get(spec.executionId)
        if existing is not None:
            return existing

        discriminator = _PROVIDER_DISCRIMINATOR[self.backend]
        if discriminator == "batch":
            detail = {
                "batch": BatchProviderDetail(
                    jobId=f"job-{spec.executionId}", taskId=spec.executionId
                )
            }
        elif discriminator == "azure_ml":
            detail = {
                "azureMl": AzureMlProviderDetail(
                    jobName=spec.executionId, workspace="ws"
                )
            }
        else:
            detail = {
                "local": LocalProviderDetail(
                    executionDirectory=f"/tmp/{spec.executionId}"
                )
            }

        handle = ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=self.backend,
            selectedBackend=self.backend,
            backendProfile="default",
            providerJobId=f"job-{spec.executionId}",
            providerTaskId=spec.executionId,
            targetId="target-1",
            outputUri=spec.outputs[0].destinationUri,
            submittedAt="2026-01-01T00:00:00+00:00",
            routingReason="adapter-default",
            attempt=1,
            providerDetail=ComputeProviderDetail(
                discriminator=discriminator, **detail
            ),
        )
        self.jobs[spec.executionId] = handle
        return handle

    def get_status(self, handle):
        self.calls.append(("get_status", handle.executionId))
        self.handles.append(("get_status", handle))
        return self.state

    def read_output(self, handle, relative_path, *, as_chunks=False):
        self.calls.append(("read_output", handle.executionId))
        self.handles.append(("read_output", handle))
        content = self.outputs.get(relative_path)
        if content is not None and as_chunks:
            return [content.encode("utf-8")]
        return content

    def cancel(self, handle):
        self.calls.append(("cancel", handle.executionId))
        self.handles.append(("cancel", handle))

    def finalize(self, handle):
        self.calls.append(("finalize", handle.executionId))
        self.handles.append(("finalize", handle))

    def get_capacity(self, workload, resources):
        self.calls.append(("get_capacity", workload.value))
        return CapacitySnapshot(
            backend=self.backend,
            workload=workload,
            state=self.capacity_state,
        )


def _service(backend=ComputeBackend.AZURE_BATCH):
    """A ``ComputeExecutionService`` wired to one fake adapter for every
    workload profile (dependency injection: no real provider)."""
    runner = RecordingRunner(backend=backend)
    registry = RunnerRegistry(Config())
    for profile in _PROFILES:
        registry.register(backend, lambda r=runner: r, profile=profile)
    return ComputeExecutionService(registry=registry), runner


def _runtime_env(**extra):
    env = {
        "COMPUTE_OUTPUT_CONTAINER_URL": CONTAINER_URL,
        "COMPUTE_IMAGE_TRAINING": "acr.example.io/haste-training:v2",
        "COMPUTE_IMAGE_IMAGERYPREP": "acr.example.io/haste-imageryprep:v2",
        "COMPUTE_BACKEND_DEFAULT": "azure_batch",
        "COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true",
    }
    env.update(extra)
    return patch.dict("os.environ", env, clear=False)


def _covered_live(spec, workspace_path):
    """True when a live-mounted declared output covers ``workspace_path``.

    Ties a submitted spec's declared outputs to the file the processor
    actually reads back: a log read during (or after) the run must sit
    inside a declared, live-mounted output, or a backend that binds
    outputs statically never makes it durable.
    """
    return any(
        fnmatch(workspace_path, output.sourceRelativePattern)
        and output.persistenceMode == OutputPersistenceMode.LIVE_MOUNT
        for output in spec.outputs
    )


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


def _training_inputs():
    return {
        "config": {
            "http_url": "https://acct.blob.core.windows.net/data/c.yaml",
            "file_path": "inputs/c.yaml",
        }
    }


def _train_processor(model, service):
    from hastegeo.core.processors import train

    with patch.object(train, "UnifiedDataLayer", autospec=True), patch.object(
        train, "AzureQueueHandler", autospec=True
    ):
        processor = train.TrainPostprocessor(
            model=model,
            image_layer=ImageLayer(
                imageLayerId="layer-1", projectId=PROJECT_ID
            ),
            config=Config(),
            execution_service=service,
        )
    processor._create_experiment_config = MagicMock(
        return_value=_training_inputs()
    )
    return processor


def _training_model(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "name": "damage-model",
        "maxEpochs": "3",
        "totalSteps": 4,
        "currentStep": 0,
        "status": STATUS.PENDING.value,
        "trainingJob": TrainingJob(
            taskId="trn-stable",
            modelId="42",
            projectId=PROJECT_ID,
            status=STATUS.PENDING.value,
            creationDate="2026-01-01T00:00:00+00:00",
        ),
    }
    values.update(overrides)
    return Model(**values)


class TestTrainingSubmission(unittest.TestCase):
    def test_preprocessor_records_a_stable_pending_task_id(self):
        from hastegeo.core.processors import train

        model = Model(
            modelId="42", projectId=PROJECT_ID, maxEpochs="2", status=None
        )
        with patch.object(train, "AzureQueueHandler", autospec=True):
            pre = train.TrainPreprocessor(model, config=Config())
            output = pre.send_to_queue()

        self.assertIsNotNone(output.trainingJob)
        self.assertTrue(output.trainingJob.taskId.startswith("trn-"))
        self.assertEqual(output.trainingJob.status, STATUS.PENDING.value)
        # The id must be on the queued payload, not minted later.
        payload = json.loads(pre.queue_client.put_message.call_args.args[0])
        self.assertEqual(
            payload["trainingJob"]["taskId"], output.trainingJob.taskId
        )

    def test_submission_uses_the_pending_task_id_and_persists_the_handle(
        self,
    ):
        service, runner = _service()
        model = _training_model()
        with _runtime_env():
            processor = _train_processor(model, service)
            result = processor.process()

        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)
        self.assertIn(("submit", "trn-stable"), runner.calls)
        job = result.trainingJob
        self.assertEqual(job.taskId, "trn-stable")
        self.assertEqual(job.jobId, "job-trn-stable")
        self.assertIsNotNone(job.computeJob)
        self.assertEqual(job.computeJob.executionId, "trn-stable")
        self.assertEqual(
            job.computeJob.selectedBackend, ComputeBackend.AZURE_BATCH
        )
        self.assertEqual(job.computeJob.backendProfile, "training")
        # Pending creationDate is preserved, not reset on submit.
        self.assertEqual(job.creationDate, "2026-01-01T00:00:00+00:00")

    def test_duplicate_delivery_reuses_the_same_provider_job(self):
        service, runner = _service()
        model = _training_model()
        with _runtime_env():
            processor = _train_processor(model, service)
            processor.process()
            # Same message delivered twice: the record still says PENDING
            # in the duplicate copy the queue re-delivers.
            duplicate = _training_model()
            duplicate.trainingJob.taskId = model.trainingJob.taskId
            processor_2 = _train_processor(duplicate, service)
            processor_2.process()

        submits = [c for c in runner.calls if c[0] == "submit"]
        self.assertEqual(len(submits), 2)
        self.assertEqual({c[1] for c in submits}, {"trn-stable"})
        # One provider job, not two.
        self.assertEqual(list(runner.jobs), ["trn-stable"])

    def test_selected_backend_is_persisted_for_follow_ons(self):
        service, _ = _service(backend=ComputeBackend.LOCAL)
        model = _training_model()
        with _runtime_env(COMPUTE_BACKEND_DEFAULT="local"):
            processor = _train_processor(model, service)
            result = processor.process()
        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)
        self.assertEqual(result.computeBackend, ComputeBackend.LOCAL)

    def test_backend_is_not_pinned_when_inheritance_is_disabled(self):
        service, _ = _service(backend=ComputeBackend.LOCAL)
        model = _training_model()
        with _runtime_env(
            COMPUTE_BACKEND_DEFAULT="local",
            COMPUTE_FOLLOW_ON_INHERITS_BACKEND="false",
        ):
            processor = _train_processor(model, service)
            result = processor.process()
        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)
        self.assertIsNone(result.computeBackend)


class TestTrainingPolling(unittest.TestCase):
    def _in_progress_model(self, **job_overrides):
        job_values = {
            "jobId": "job-trn-stable",
            "taskId": "trn-stable",
            "modelId": "42",
            "projectId": PROJECT_ID,
            "status": STATUS.IN_PROGRESS.value,
        }
        job_values.update(job_overrides)
        return _training_model(
            status=STATUS.IN_PROGRESS.value,
            trainingJob=TrainingJob(**job_values),
        )

    def _submitted_model(self, service):
        model = _training_model()
        with _runtime_env():
            _train_processor(model, service).process()
        model.status = STATUS.IN_PROGRESS.value
        return model

    def test_succeeded_maps_to_processed_and_sets_artifact_paths(self):
        service, runner = _service()
        model = self._submitted_model(service)
        runner.state = ComputeJobState.SUCCEEDED
        with _runtime_env():
            result = _train_processor(model, service).process()

        self.assertEqual(result.status, STATUS.COMPLETED.value)
        self.assertEqual(
            result.trainingOutputPath,
            output_prefix(PROJECT_ID, "trn-stable"),
        )
        self.assertEqual(
            result.checkpointPath,
            f"{output_prefix(PROJECT_ID, 'trn-stable')}/checkpoint",
        )
        self.assertIn("finalize", [call[0] for call in runner.handles])

    def test_failed_maps_to_failed_and_reports_progress_errors(self):
        service, runner = _service()
        model = self._submitted_model(service)
        runner.state = ComputeJobState.FAILED
        runner.outputs[
            "workflow_progress.log"
        ] = "2026-01-01|Unexpected error while training\n"
        with _runtime_env():
            result = _train_processor(model, service).process()

        self.assertEqual(result.status, STATUS.FAILED.value)
        self.assertIn("Unexpected error while training", result.statusMessage)

    def test_cancelled_state_maps_to_the_cancelled_status(self):
        service, runner = _service()
        model = self._submitted_model(service)
        runner.state = ComputeJobState.CANCELLED
        with _runtime_env():
            result = _train_processor(model, service).process()
        self.assertEqual(result.status, STATUS.CANCELLED.value)

    def test_running_state_keeps_the_job_in_progress(self):
        service, runner = _service()
        model = self._submitted_model(service)
        runner.state = ComputeJobState.RUNNING
        with _runtime_env():
            result = _train_processor(model, service).process()
        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)

    def test_lifecycle_uses_the_persisted_handle(self):
        service, runner = _service()
        model = self._submitted_model(service)
        runner.state = ComputeJobState.RUNNING
        with _runtime_env():
            _train_processor(model, service).process()

        _, handle = runner.handles[0]
        self.assertEqual(handle.executionId, "trn-stable")
        self.assertEqual(handle.backendProfile, "training")
        self.assertNotEqual(handle.routingReason, "legacy-synthesized")

    def test_legacy_record_falls_back_to_a_synthesized_batch_handle(self):
        service, runner = _service()
        # Pre-compute-layer record: jobId/taskId only, no computeJob.
        model = self._in_progress_model()
        runner.state = ComputeJobState.RUNNING
        with _runtime_env():
            _train_processor(model, service).process()

        _, handle = runner.handles[0]
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(handle.routingReason, "legacy-synthesized")
        self.assertEqual(handle.providerJobId, "job-trn-stable")
        self.assertEqual(handle.providerTaskId, "trn-stable")
        # Synthesis requires real output context, which the processor
        # supplies from configuration + the record's own task id.
        self.assertEqual(
            handle.outputUri,
            f"{CONTAINER_URL}/{output_prefix(PROJECT_ID, 'trn-stable')}",
        )

    def test_missing_submission_raises_instead_of_silently_polling(self):
        service, _ = _service()
        model = _training_model(status=STATUS.IN_PROGRESS.value)
        model.trainingJob = TrainingJob(taskId="trn-stable")
        with _runtime_env():
            with self.assertRaises(ValueError):
                _train_processor(model, service).process()


class TestTrainingCancellation(unittest.TestCase):
    def test_cancel_requests_provider_cancellation_and_finalizes(self):
        service, runner = _service()
        model = _training_model()
        with _runtime_env():
            processor = _train_processor(model, service)
            processor.process()
            model.status = STATUS.IN_PROGRESS.value
            result = _train_processor(model, service).cancel()

        actions = [call[0] for call in runner.handles]
        self.assertIn("cancel", actions)
        self.assertIn("finalize", actions)
        self.assertEqual(result.status, STATUS.CANCELLED.value)
        self.assertEqual(result.trainingJob.status, STATUS.CANCELLED.value)

    def test_cancel_before_submission_contacts_no_provider(self):
        service, runner = _service()
        model = _training_model()
        with _runtime_env():
            result = _train_processor(model, service).cancel()

        self.assertEqual(result.status, STATUS.CANCELLED.value)
        self.assertEqual(runner.handles, [])


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


def _inference_processor(model, service):
    from hastegeo.core.processors import inference

    with patch.object(
        inference, "UnifiedDataLayer", autospec=True
    ), patch.object(inference, "AzureQueueHandler", autospec=True):
        processor = inference.InferencePostprocessor(
            model=model,
            image_layer=ImageLayer(
                imageLayerId="layer-1",
                projectId=PROJECT_ID,
                buildingFootprintsUrl="https://acct/c/f.gpkg?sig=x",
            ),
            config=Config(),
            execution_service=service,
        )
    processor._create_inference_config = MagicMock(
        return_value=_training_inputs()
    )
    return processor


def _inference_model(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "name": "damage-model",
        "status": STATUS.COMPLETED.value,
        "inferenceStatus": STATUS.PENDING.value,
        "inferenceTotalSteps": 7,
        "inferenceCurrentStep": 0,
        "currentInferenceTaskId": "inf-stable",
        "inferenceJobs": [
            InferenceJob(
                taskId="inf-stable",
                modelId="42",
                projectId=PROJECT_ID,
                status=STATUS.PENDING.value,
                creationDate="2026-01-01T00:00:00+00:00",
            )
        ],
    }
    values.update(overrides)
    return Model(**values)


class TestInferenceLifecycle(unittest.TestCase):
    def test_preprocessor_creates_the_pending_job_and_current_task_id(self):
        from hastegeo.core.processors import inference

        model = Model(modelId="42", projectId=PROJECT_ID)
        with patch.object(inference, "AzureQueueHandler", autospec=True):
            output = inference.InferencePreprocessor(
                model, config=Config()
            ).send_to_queue()

        self.assertEqual(len(output.inferenceJobs), 1)
        self.assertTrue(output.inferenceJobs[0].taskId.startswith("inf-"))
        self.assertEqual(
            output.currentInferenceTaskId, output.inferenceJobs[0].taskId
        )
        self.assertEqual(output.inferenceStatus, STATUS.PENDING.value)

    def test_cancellation_request_does_not_create_a_new_job(self):
        from hastegeo.core.processors import inference

        model = _inference_model()
        with patch.object(inference, "AzureQueueHandler", autospec=True):
            output = inference.InferencePreprocessor(
                model, config=Config()
            ).send_to_queue(status=STATUS.CANCELLED.value)

        self.assertEqual(output.inferenceStatus, STATUS.CANCELLED.value)
        self.assertEqual(len(output.inferenceJobs), 1)

    def test_submission_replaces_the_pending_record_in_place(self):
        service, runner = _service()
        model = _inference_model()
        with _runtime_env():
            result = _inference_processor(model, service).process()

        self.assertIn(("submit", "inf-stable"), runner.calls)
        self.assertEqual(len(result.inferenceJobs), 1)
        job = result.inferenceJobs[0]
        self.assertEqual(job.taskId, "inf-stable")
        self.assertIsNotNone(job.computeJob)
        self.assertEqual(job.computeJob.backendProfile, "inference")
        self.assertEqual(result.inferenceStatus, STATUS.IN_PROGRESS.value)

    def test_completion_sets_result_urls_from_the_task_prefix(self):
        service, runner = _service()
        model = _inference_model()
        with _runtime_env():
            _inference_processor(model, service).process()
            model.inferenceStatus = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.SUCCEEDED
            processor = _inference_processor(model, service)
            result = processor.process()

        self.assertEqual(result.inferenceStatus, STATUS.COMPLETED.value)
        self.assertEqual(
            result.inferenceOutputPath,
            output_prefix(PROJECT_ID, "inf-stable"),
        )
        _, kwargs = processor.storage.get_file_remote_path.call_args
        # Remote backends keep the flat task-id partition.
        self.assertEqual(kwargs["extra_partition_keys"], "inf-stable")

    def test_local_backend_results_use_the_inference_subfolder(self):
        service, runner = _service(backend=ComputeBackend.LOCAL)
        model = _inference_model()
        with _runtime_env(COMPUTE_BACKEND_DEFAULT="local"):
            _inference_processor(model, service).process()
            self.assertEqual(model.inferenceStatus, STATUS.IN_PROGRESS.value)
            runner.state = ComputeJobState.SUCCEEDED
            processor = _inference_processor(model, service)
            processor.process()

        _, kwargs = processor.storage.get_file_remote_path.call_args
        self.assertEqual(
            kwargs["extra_partition_keys"], ["inf-stable", "inference"]
        )

    def test_legacy_local_job_keeps_the_inference_subfolder(self):
        # A job submitted before the compute layer existed has only
        # jobId/taskId, so its handle is synthesized as Batch; on a local
        # deployment its result URLs must still resolve the way they did
        # before the upgrade.
        service, runner = _service()
        model = _inference_model(
            inferenceStatus=STATUS.IN_PROGRESS.value,
            inferenceJobs=[
                InferenceJob(
                    jobId="job-inf-stable",
                    taskId="inf-stable",
                    modelId="42",
                    projectId=PROJECT_ID,
                    status=STATUS.IN_PROGRESS.value,
                )
            ],
        )
        runner.state = ComputeJobState.SUCCEEDED
        with _runtime_env(RUNNER_TYPE="local"):
            processor = _inference_processor(model, service)
            processor.process()

        _, kwargs = processor.storage.get_file_remote_path.call_args
        self.assertEqual(
            kwargs["extra_partition_keys"], ["inf-stable", "inference"]
        )

    def test_progress_log_lines_reach_the_status_message(self):
        service, runner = _service()
        model = _inference_model()
        runner.outputs[
            "workflow_progress.log"
        ] = "2026-01-01T00:00:00|Running inference\n"
        with _runtime_env():
            _inference_processor(model, service).process()
            model.inferenceStatus = STATUS.IN_PROGRESS.value
            result = _inference_processor(model, service).process()

        self.assertIn("Running inference", result.inferenceStatusMessage)

    def test_the_progress_log_read_is_covered_by_a_declared_output(self):
        # The log the processor reads must sit inside a declared,
        # live-mounted output: a backend that binds outputs statically
        # (Azure ML) only makes a declared directory durable, so without
        # it both the live progress and the post-mortem failure detail
        # are lost.
        service, runner = _service()
        model = _inference_model()
        runner.outputs[
            "workflow_progress.log"
        ] = "2026-01-01T00:00:00|Running inference\n"
        with _runtime_env():
            _inference_processor(model, service).process()
            spec = runner.specs[-1]
            model.inferenceStatus = STATUS.IN_PROGRESS.value
            _inference_processor(model, service).process()

        self.assertIn(
            ("read_output", "inf-stable"),
            [call[:2] for call in runner.calls],
        )
        self.assertTrue(
            _covered_live(spec, "logs/workflow_progress.log"),
            [o.sourceRelativePattern for o in spec.outputs],
        )
        self.assertIn(
            f"{CONTAINER_URL}/{output_prefix(PROJECT_ID, 'inf-stable')}",
            {o.destinationUri for o in spec.outputs},
        )

    def test_failure_detail_still_reads_after_the_job_ends(self):
        service, runner = _service()
        model = _inference_model()
        runner.outputs["stderr.txt"] = "traceback"
        with _runtime_env():
            _inference_processor(model, service).process()
            spec = runner.specs[-1]
            model.inferenceStatus = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.FAILED
            result = _inference_processor(model, service).process()

        self.assertEqual(result.inferenceStatus, STATUS.FAILED.value)
        self.assertTrue(_covered_live(spec, "logs/workflow_progress.log"))

    def test_cancel_uses_the_persisted_handle(self):
        service, runner = _service()
        model = _inference_model()
        with _runtime_env():
            _inference_processor(model, service).process()
            model.inferenceStatus = STATUS.IN_PROGRESS.value
            result = _inference_processor(model, service).cancel()

        self.assertIn("cancel", [call[0] for call in runner.handles])
        self.assertEqual(result.inferenceStatus, STATUS.CANCELLED.value)
        self.assertEqual(
            result.inferenceJobs[0].status, STATUS.CANCELLED.value
        )


# --------------------------------------------------------------------------
# Embedding
# --------------------------------------------------------------------------


def _embedding_processor(model, service):
    from hastegeo.core.processors import embedding

    with patch.object(
        embedding, "UnifiedDataLayer", autospec=True
    ), patch.object(embedding, "AzureQueueHandler", autospec=True):
        processor = embedding.EmbeddingPostprocessor(
            model=model,
            image_layer=ImageLayer(
                imageLayerId="layer-1",
                projectId=PROJECT_ID,
                postEventMosaicCogImageryUrl="https://acct/c/mosaic.tif?sig=x",
                buildingFootprintsUrl="https://acct/c/f.gpkg?sig=x",
            ),
            config=Config(),
            execution_service=service,
        )
    processor._create_embedding_config = MagicMock(
        return_value=_training_inputs()
    )
    processor.storage.get_file_remote_path.return_value = (
        "https://acct.blob.core.windows.net/data/hash/emb.geojson"
    )
    return processor


def _embedding_model(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "name": "embedding-run",
        "modelType": "embedding",
        "status": STATUS.PENDING.value,
        "currentStep": 0,
        "totalSteps": 3,
        "embeddingJob": TrainingJob(
            taskId="emb-stable",
            modelId="42",
            projectId=PROJECT_ID,
            status=STATUS.PENDING.value,
            creationDate="2026-01-01T00:00:00+00:00",
        ),
    }
    values.update(overrides)
    return Model(**values)


_EMBEDDING_MANIFEST = json.dumps(
    {
        "embeddings_filename": "emb.geojson",
        "pmtiles_filename": "emb.pmtiles",
        "sidecar_filename": "emb.bin",
        "num_buildings": 12,
        "num_features": 1024,
    }
)


class TestEmbeddingLifecycle(unittest.TestCase):
    def test_preprocessor_records_a_pending_job(self):
        from hastegeo.core.processors import embedding

        model = Model(modelId="42", projectId=PROJECT_ID)
        with patch.object(embedding, "AzureQueueHandler", autospec=True):
            output = embedding.EmbeddingPreprocessor(
                model, config=Config()
            ).send_to_queue()

        self.assertIsNotNone(output.embeddingJob)
        self.assertTrue(output.embeddingJob.taskId.startswith("emb-"))

    def test_submission_reuses_the_pending_id_and_persists_the_handle(self):
        service, runner = _service()
        model = _embedding_model()
        with _runtime_env():
            result = _embedding_processor(model, service).process()

        self.assertIn(("submit", "emb-stable"), runner.calls)
        self.assertEqual(result.embeddingJob.taskId, "emb-stable")
        self.assertIsNotNone(result.embeddingJob.computeJob)
        self.assertEqual(
            result.embeddingJob.computeJob.backendProfile, "embedding"
        )
        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)

    def test_friendly_log_is_declared_durable_and_still_read(self):
        # embed_buildings writes logs/embedding_friendly.log; the
        # processor surfaces it in the status message, so it must sit
        # inside a declared, live-mounted output.
        service, runner = _service()
        model = _embedding_model()
        runner.outputs["embedding_manifest.json"] = _EMBEDDING_MANIFEST
        runner.outputs[
            "embedding_friendly.log"
        ] = "2026-01-01T00:00:00|Embedding buildings\n"

        with _runtime_env():
            _embedding_processor(model, service).process()
            spec = runner.specs[-1]
            model.status = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.SUCCEEDED
            result = _embedding_processor(model, service).process()

        self.assertEqual(result.status, STATUS.COMPLETED.value)
        self.assertIn("Embedding buildings", result.statusMessage)
        self.assertTrue(
            _covered_live(spec, "logs/embedding_friendly.log"),
            [o.sourceRelativePattern for o in spec.outputs],
        )
        # The manifest keeps its own declared output, at the same prefix.
        self.assertTrue(_covered_live(spec, "outputs/embedding_manifest.json"))
        self.assertEqual(
            {o.destinationUri for o in spec.outputs},
            {f"{CONTAINER_URL}/{output_prefix(PROJECT_ID, 'emb-stable')}"},
        )

    def test_failure_reports_the_friendly_log_too(self):
        service, runner = _service()
        model = _embedding_model()
        runner.outputs[
            "embedding_friendly.log"
        ] = "2026-01-01T00:00:00|Ran out of memory\n"

        with _runtime_env():
            _embedding_processor(model, service).process()
            spec = runner.specs[-1]
            model.status = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.FAILED
            result = _embedding_processor(model, service).process()

        self.assertEqual(result.status, STATUS.FAILED.value)
        self.assertIn("Ran out of memory", result.statusMessage)
        self.assertTrue(_covered_live(spec, "logs/embedding_friendly.log"))


# --------------------------------------------------------------------------
# Imagery preparation
# --------------------------------------------------------------------------


def _imagery_processor(image_layer, service):
    from hastegeo.core.processors import imagery

    with patch.object(
        imagery, "UnifiedDataLayer", autospec=True
    ), patch.object(imagery, "AzureQueueHandler", autospec=True):
        processor = imagery.ImageryPostProcessor(
            image_data=image_layer,
            config=Config(),
            execution_service=service,
        )
    processor.storage.get_file_remote_path.return_value = (
        "https://acct.blob.core.windows.net/data/hash/config.yaml?sig=x"
    )
    return processor


def _image_layer(**overrides):
    values = {
        "imageLayerId": "layer-1",
        "projectId": PROJECT_ID,
        "status": STATUS.PENDING.value,
        "currentStep": 0,
        "totalSteps": 4,
        "preprocessJob": ImageryPreprocessJob(
            taskId="img-stable",
            imageLayerId="layer-1",
            projectId=PROJECT_ID,
            status=STATUS.PENDING.value,
            creationDate="2026-01-01T00:00:00+00:00",
        ),
    }
    values.update(overrides)
    return ImageLayer(**values)


class TestImageryLifecycle(unittest.TestCase):
    def test_preprocessor_records_a_pending_job(self):
        from hastegeo.core.processors import imagery

        layer = ImageLayer(imageLayerId="layer-1", projectId=PROJECT_ID)
        with patch.object(imagery, "AzureQueueHandler", autospec=True):
            output = imagery.ImageryPreProcessor(
                image_data=layer, config=Config()
            ).queue_for_processing()

        self.assertIsNotNone(output.preprocessJob)
        self.assertTrue(output.preprocessJob.taskId.startswith("img-"))

    def test_submission_reuses_the_pending_id_and_persists_the_handle(self):
        service, runner = _service()
        layer = _image_layer()
        with _runtime_env():
            result = _imagery_processor(layer, service).process()

        self.assertIn(("submit", "img-stable"), runner.calls)
        self.assertEqual(result.preprocessJob.taskId, "img-stable")
        self.assertIsNotNone(result.preprocessJob.computeJob)
        self.assertEqual(
            result.preprocessJob.computeJob.backendProfile, "imageryprep"
        )
        self.assertEqual(result.status, STATUS.IN_PROGRESS.value)

    def test_completion_reads_the_manifest_through_the_service(self):
        service, runner = _service()
        layer = _image_layer()
        manifest = {
            "preview_pre_event_filenames": [],
            "preview_post_event_filenames": [],
            "pre_event_mosaic_filename": "",
            "pre_event_processed_filename": "",
            "post_event_mosaic_filename": "",
            "post_event_processed_filename": "",
            "normalization_means": [1.0],
            "normalization_stds": [2.0],
            "building_footprints_filename": "",
            "building_footprints_error": "",
            "valid_area_mask_filename": "",
        }
        with _runtime_env():
            _imagery_processor(layer, service).process()
            layer.status = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.SUCCEEDED
            runner.outputs["imagery_manifest.json"] = json.dumps(manifest)
            result = _imagery_processor(layer, service).process()

        self.assertEqual(result.status, STATUS.COMPLETED.value)
        self.assertEqual(result.normalizationMeans, [1.0])

    def test_legacy_record_polls_through_a_synthesized_handle(self):
        service, runner = _service()
        layer = _image_layer(
            status=STATUS.IN_PROGRESS.value,
            preprocessJob=ImageryPreprocessJob(
                jobId="imageryprep-pool",
                taskId="img-stable",
                imageLayerId="layer-1",
                projectId=PROJECT_ID,
                status=STATUS.IN_PROGRESS.value,
            ),
        )
        runner.state = ComputeJobState.RUNNING
        with _runtime_env():
            _imagery_processor(layer, service).process()

        _, handle = runner.handles[0]
        self.assertEqual(handle.routingReason, "legacy-synthesized")
        self.assertEqual(handle.providerJobId, "imageryprep-pool")


# --------------------------------------------------------------------------
# Artifact packaging
# --------------------------------------------------------------------------


def _artifact_processor(model, model_artifacts, service):
    from hastegeo.core.processors import artifacts

    with patch.object(
        artifacts, "UnifiedArtifactStorage", autospec=True
    ), patch.object(artifacts, "AzureQueueHandler", autospec=True):
        processor = artifacts.ArtifactProcessor(
            partition_key=PROJECT_ID,
            config=Config(),
            model=model,
            model_artifacts=model_artifacts,
            execution_service=service,
        )
    processor.storage.get_base_url.return_value = CONTAINER_URL
    return processor


def _model_artifacts(**overrides):
    values = {
        "modelId": "42",
        "projectId": PROJECT_ID,
        "imageLayerId": "layer-1",
        "zipStatus": STATUS.PENDING.value,
        "currentZipJobUid": "zip-stable",
        "zipJobs": [
            ZipJob(
                projectId=PROJECT_ID,
                imageLayerId="layer-1",
                modelId="42",
                taskId="zip-stable",
                status=STATUS.PENDING.value,
                dstZipPath=output_prefix(PROJECT_ID, "zip-stable"),
                creationDate="2026-01-01T00:00:00+00:00",
            )
        ],
    }
    values.update(overrides)
    return ModelArtifacts(**values)


class TestArtifactPackagingLifecycle(unittest.TestCase):
    def _model(self):
        return Model(
            modelId="42",
            projectId=PROJECT_ID,
            imageLayerId="layer-1",
            name="damage-model",
            trainingOutputPath=output_prefix(PROJECT_ID, "trn-1"),
            inferenceOutputPath=output_prefix(PROJECT_ID, "inf-1"),
        )

    def test_queueing_records_a_pending_zip_job(self):
        from hastegeo.core.processors import artifacts

        model_artifacts = ModelArtifacts(
            modelId="42", projectId=PROJECT_ID, imageLayerId="layer-1"
        )
        with patch.object(
            artifacts, "UnifiedArtifactStorage", autospec=True
        ), patch.object(artifacts, "AzureQueueHandler", autospec=True):
            output = artifacts.ArtifactProcessor(
                partition_key=PROJECT_ID,
                model_artifacts=model_artifacts,
            ).send_to_zip_queue()

        self.assertEqual(len(output.zipJobs), 1)
        self.assertTrue(output.zipJobs[0].taskId.startswith("zip-"))
        self.assertEqual(output.currentZipJobUid, output.zipJobs[0].taskId)
        self.assertEqual(
            output.zipJobs[0].dstZipPath,
            output_prefix(PROJECT_ID, output.zipJobs[0].taskId),
        )

    def test_submission_reuses_the_pending_id_and_records_sources(self):
        service, runner = _service()
        model_artifacts = _model_artifacts()
        with _runtime_env():
            result = _artifact_processor(
                self._model(), model_artifacts, service
            ).process_zip()

        self.assertIn(("submit", "zip-stable"), runner.calls)
        self.assertEqual(len(result.zipJobs), 1)
        job = result.zipJobs[0]
        self.assertEqual(job.taskId, "zip-stable")
        self.assertEqual(
            job.srcArtifactPaths,
            [
                output_prefix(PROJECT_ID, "trn-1"),
                output_prefix(PROJECT_ID, "inf-1"),
            ],
        )
        self.assertIsNotNone(job.computeJob)
        self.assertEqual(job.computeJob.backendProfile, "artifacts")

    def test_explicit_backend_on_the_record_is_honored(self):
        service, runner = _service(backend=ComputeBackend.LOCAL)
        model_artifacts = _model_artifacts(computeBackend=ComputeBackend.LOCAL)
        with _runtime_env():
            result = _artifact_processor(
                self._model(), model_artifacts, service
            ).process_zip()

        self.assertEqual(
            result.zipJobs[0].computeJob.selectedBackend,
            ComputeBackend.LOCAL,
        )

    def test_completion_reads_the_manifest_and_finalizes(self):
        service, runner = _service()
        model_artifacts = _model_artifacts()
        with _runtime_env():
            processor = _artifact_processor(
                self._model(), model_artifacts, service
            )
            processor.process_zip()
            model_artifacts.zipStatus = STATUS.IN_PROGRESS.value
            runner.state = ComputeJobState.SUCCEEDED
            processor = _artifact_processor(
                self._model(), model_artifacts, service
            )
            processor._read_zip_manifest = MagicMock(
                return_value={
                    "training_zip": {
                        "filename": "training.zip",
                        "size_bytes": 10,
                    }
                }
            )
            result = processor.process_zip()

        self.assertEqual(result.zipStatus, STATUS.COMPLETED.value)
        self.assertEqual(result.trainingZipSize, 10)
        self.assertIn("finalize", [call[0] for call in runner.handles])


if __name__ == "__main__":
    unittest.main()
