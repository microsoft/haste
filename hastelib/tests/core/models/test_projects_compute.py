# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the additive compute-layer fields on
``hastegeo.core.models.projects``:

- ``computeJob: Optional[ComputeJobHandle]`` on ``TrainingJob``,
  ``InferenceJob``, ``ImageryPreprocessJob``, ``ZipJob``;
- ``computeBackend: Optional[ComputeBackend]`` on ``Model``,
  ``ImageLayer``, ``ModelArtifacts``.

Covers: legacy records (no ``computeJob``/``computeBackend`` key at all)
still deserialize unchanged, new records with either field round-trip
through ``model_dump``/reconstruction, and defaults are ``None`` so
existing payloads are unaffected. See
spec/features/aml-compute-backend/data-model.md#modified-module-
hastegeocoremodelsprojects.
"""

import unittest

from hastegeo.core.models.compute import (
    BatchProviderDetail,
    ComputeBackend,
    ComputeJobHandle,
    ComputeProviderDetail,
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
from pydantic import ValidationError


def _handle(**overrides) -> ComputeJobHandle:
    kwargs = dict(
        executionId="exec-abc-123",
        requestedBackend=ComputeBackend.AZURE_BATCH,
        selectedBackend=ComputeBackend.AZURE_BATCH,
        backendProfile="default",
        providerJobId="job-1",
        providerTaskId="task-1",
        targetId="pool-1",
        outputUri="https://acct.blob.core.windows.net/c/out/",
        submittedAt="2026-01-01T00:00:00+00:00",
        routingReason="explicit",
        attempt=1,
        providerDetail=ComputeProviderDetail(
            discriminator="batch",
            batch=BatchProviderDetail(jobId="job-1", taskId="task-1"),
        ),
    )
    kwargs.update(overrides)
    return ComputeJobHandle(**kwargs)


# Every job model that gained a ``computeJob`` field, paired with a legacy
# payload that only carries the pre-existing ``jobId``/``taskId`` strings.
_JOB_MODEL_CASES = (
    (TrainingJob, {"trainingjobUid": "train-1"}),
    (InferenceJob, {"uid": "inf-1"}),
    (ImageryPreprocessJob, {"projectId": "proj-1"}),
    (ZipJob, {"uid": "zip-1"}),
)


class TestJobModelsComputeJobField(unittest.TestCase):
    """``computeJob`` defaults to ``None`` and round-trips when set, for
    every one of the four job models. ``jobId``/``taskId`` are retained
    unchanged either way."""

    def test_default_is_none_for_every_job_model(self):
        for model_cls, extra in _JOB_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                job = model_cls(**extra)
                self.assertIsNone(job.computeJob)

    def test_legacy_record_without_computeJob_key_deserializes_unchanged(
        self,
    ):
        """A pre-existing Cosmos document shape (only jobId/taskId, no
        computeJob key present at all) must still validate, with jobId/
        taskId preserved and computeJob defaulting to None."""
        for model_cls, extra in _JOB_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                legacy_payload = dict(extra, jobId="job-42", taskId="task-7")
                job = model_cls(**legacy_payload)
                self.assertEqual(job.jobId, "job-42")
                self.assertEqual(job.taskId, "task-7")
                self.assertIsNone(job.computeJob)

    def test_new_record_round_trips_computeJob_handle(self):
        handle = _handle()
        for model_cls, extra in _JOB_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                job = model_cls(
                    jobId="job-1", taskId="task-1", computeJob=handle, **extra
                )
                payload = job.model_dump()
                self.assertEqual(
                    payload["computeJob"]["providerJobId"], "job-1"
                )
                restored = model_cls(**payload)
                self.assertEqual(restored.computeJob, handle)
                self.assertEqual(restored.jobId, "job-1")
                self.assertEqual(restored.taskId, "task-1")

    def test_new_record_round_trips_through_json(self):
        handle = _handle()
        for model_cls, extra in _JOB_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                job = model_cls(computeJob=handle, **extra)
                restored = model_cls.model_validate_json(job.model_dump_json())
                self.assertEqual(restored.computeJob, handle)

    def test_client_supplied_computeJob_must_match_handle_shape(self):
        # Not an API-layer authorization test (that lives with the HTTP
        # endpoints) — this only confirms the model itself still enforces
        # ComputeJobHandle's own validation (e.g. rejecting 'auto' as a
        # selected backend) when a computeJob payload is supplied.
        for model_cls, extra in _JOB_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                bad_handle = _handle().model_dump()
                bad_handle["selectedBackend"] = "auto"
                with self.assertRaises(ValidationError):
                    model_cls(computeJob=bad_handle, **extra)


# Every parent request-bearing record that gained a computeBackend field.
_REQUEST_MODEL_CASES = (
    (Model, {"modelId": "model-1"}),
    (ImageLayer, {"imageLayerId": "layer-1"}),
    (ModelArtifacts, {"modelId": "model-1"}),
)


class TestRequestModelsComputeBackendField(unittest.TestCase):
    """``computeBackend`` is additive on ``Model``/``ImageLayer``/
    ``ModelArtifacts``: defaults to ``None`` (existing payloads
    unchanged), accepts an explicit ``ComputeBackend`` value, and
    round-trips through serialization."""

    def test_default_is_none_for_every_request_model(self):
        for model_cls, extra in _REQUEST_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                record = model_cls(**extra)
                self.assertIsNone(record.computeBackend)

    def test_legacy_payload_without_computeBackend_key_is_unchanged(self):
        for model_cls, extra in _REQUEST_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                record = model_cls(**extra)
                self.assertIsNone(record.computeBackend)
                self.assertNotIn("computeBackend", extra)

    def test_accepts_and_round_trips_explicit_backend(self):
        for model_cls, extra in _REQUEST_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                record = model_cls(
                    computeBackend=ComputeBackend.AZURE_ML, **extra
                )
                self.assertEqual(
                    record.computeBackend, ComputeBackend.AZURE_ML
                )
                payload = record.model_dump()
                self.assertEqual(payload["computeBackend"], "azure_ml")
                restored = model_cls(**payload)
                self.assertEqual(
                    restored.computeBackend, ComputeBackend.AZURE_ML
                )

    def test_accepts_auto_backend_value(self):
        # Unlike ComputeJobHandle.selectedBackend, a request-side
        # preference is allowed to be 'auto' (it is resolved to a
        # concrete backend only once a ComputeJobHandle is persisted).
        for model_cls, extra in _REQUEST_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                record = model_cls(computeBackend=ComputeBackend.AUTO, **extra)
                self.assertEqual(record.computeBackend, ComputeBackend.AUTO)

    def test_rejects_unrecognized_backend_value(self):
        for model_cls, extra in _REQUEST_MODEL_CASES:
            with self.subTest(model=model_cls.__name__):
                with self.assertRaises(ValidationError):
                    model_cls(computeBackend="not-a-real-backend", **extra)


if __name__ == "__main__":
    unittest.main()
