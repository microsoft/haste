# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ``hastegeo.core.utils.compute_jobs``:
``resolve_compute_job_handle`` (uniform read-time resolution of a job
record's compute submission, old or new shape) and
``derive_execution_id`` (deterministic, executionId-safe identifier
generation).

See spec/features/aml-compute-backend/data-model.md#legacy-compatibility.
"""

import re

import pytest
from hastegeo.core.models.compute import (
    BatchProviderDetail,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeProviderDetail,
)
from hastegeo.core.models.projects import TrainingJob
from hastegeo.core.utils.compute_jobs import (
    IMAGE_LAYER_WORKFLOW_OWNED_FIELDS,
    authoritative_job_history,
    clear_compute_handles,
    derive_execution_id,
    preserve_workflow_owned_fields,
    resolve_compute_job_handle,
    selected_backend_of,
)

_OUTPUT_URI = "https://acct.blob.core.windows.net/c/out/"


def _handle(**overrides) -> ComputeJobHandle:
    """Minimal, self-contained ``ComputeJobHandle`` fixture.

    Deliberately duplicated (not imported) from
    ``tests/core/models/test_projects_compute.py``: importing one test
    module from another isn't reliably collectable under Hatch's test
    runner, and this module has no other dependency on that one.
    """
    kwargs = dict(
        executionId="exec-abc-123",
        requestedBackend=ComputeBackend.AZURE_BATCH,
        selectedBackend=ComputeBackend.AZURE_BATCH,
        backendProfile="default",
        providerJobId="job-1",
        providerTaskId="task-1",
        targetId="pool-1",
        outputUri=_OUTPUT_URI,
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


class TestResolveComputeJobHandle:
    def test_returns_existing_handle_when_present(self):
        handle = _handle()
        job = TrainingJob(jobId="ignored", taskId="ignored", computeJob=handle)

        resolved = resolve_compute_job_handle(job, output_uri=_OUTPUT_URI)

        assert resolved is handle

    def test_existing_handle_takes_priority_even_without_output_uri(self):
        handle = _handle()
        job = TrainingJob(computeJob=handle)

        assert resolve_compute_job_handle(job) is handle

    def test_synthesizes_legacy_handle_when_output_uri_supplied(self):
        job = TrainingJob(jobId="job-42", taskId="task-7")

        resolved = resolve_compute_job_handle(job, output_uri=_OUTPUT_URI)

        assert resolved is not None
        assert resolved.selectedBackend == ComputeBackend.AZURE_BATCH
        assert resolved.providerDetail.batch.jobId == "job-42"
        assert resolved.providerDetail.batch.taskId == "task-7"
        assert resolved.outputUri == _OUTPUT_URI

    def test_synthesized_handle_uses_target_id_when_supplied(self):
        job = TrainingJob(jobId="job-42", taskId="task-7")

        resolved = resolve_compute_job_handle(
            job, output_uri=_OUTPUT_URI, target_id="pool-custom"
        )

        assert resolved.targetId == "pool-custom"

    def test_synthesized_handle_defaults_target_id_to_job_id(self):
        job = TrainingJob(jobId="job-42", taskId="task-7")

        resolved = resolve_compute_job_handle(job, output_uri=_OUTPUT_URI)

        assert resolved.targetId == "job-42"

    def test_returns_none_without_output_uri_even_with_legacy_ids(self):
        # No output_uri means there isn't enough context to synthesize a
        # valid ComputeJobHandle (outputUri is a required field) — the
        # helper must not guess/fabricate one.
        job = TrainingJob(jobId="job-42", taskId="task-7")

        assert resolve_compute_job_handle(job) is None

    def test_returns_none_when_job_id_missing(self):
        job = TrainingJob(taskId="task-7")

        assert resolve_compute_job_handle(job, output_uri=_OUTPUT_URI) is None

    def test_returns_none_when_task_id_missing(self):
        job = TrainingJob(jobId="job-42")

        assert resolve_compute_job_handle(job, output_uri=_OUTPUT_URI) is None

    def test_returns_none_for_a_not_yet_submitted_job(self):
        # No computeJob, no jobId/taskId, no output_uri: the normal shape
        # of a job record that hasn't been submitted yet. Must not raise.
        job = TrainingJob()

        assert resolve_compute_job_handle(job) is None
        assert resolve_compute_job_handle(job, output_uri=_OUTPUT_URI) is None

    def test_works_against_every_job_model_shape(self):
        # resolve_compute_job_handle is written against a structural
        # protocol, not a hard TrainingJob import — exercise the other
        # three job models too.
        from hastegeo.core.models.projects import (
            ImageryPreprocessJob,
            InferenceJob,
            ZipJob,
        )

        for model_cls in (InferenceJob, ImageryPreprocessJob, ZipJob):
            job = model_cls(jobId="job-42", taskId="task-7")
            resolved = resolve_compute_job_handle(job, output_uri=_OUTPUT_URI)
            assert resolved is not None
            assert resolved.providerJobId == "job-42"


class TestDeriveExecutionId:
    _EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

    # Azure Batch task IDs are capped at 64 characters, and the Batch
    # adapter uses ``ComputeJobSpec.executionId`` verbatim as the task ID
    # (``AzureBatchRunner.submit``) — this is the same ceiling
    # ``derive_execution_id`` itself enforces.
    _BATCH_TASK_ID_MAX_LENGTH = 64

    def test_deterministic_for_same_parts(self):
        first = derive_execution_id("training", "model-123")
        second = derive_execution_id("training", "model-123")

        assert first == second

    def test_differs_for_different_parts(self):
        assert derive_execution_id("training", "model-123") != (
            derive_execution_id("training", "model-124")
        )

    def test_differs_by_part_order(self):
        assert derive_execution_id("a", "b") != derive_execution_id("b", "a")

    def test_result_matches_execution_id_safe_charset(self):
        result = derive_execution_id("training", "model-123")

        assert self._EXECUTION_ID_RE.match(result)

    def test_sanitizes_unsafe_characters_in_human_prefix(self):
        result = derive_execution_id("train/embedding job!!", "uid")

        assert self._EXECUTION_ID_RE.match(result)

    def test_raises_when_every_part_is_blank(self):
        with pytest.raises(ValueError):
            derive_execution_id("", "   ", None)

    def test_ignores_blank_parts_when_deriving(self):
        # A blank part contributes nothing to identity — dropping it
        # keeps the id deterministic across callers that may or may not
        # pass an empty optional segment.
        assert derive_execution_id("training", "", "model-123") == (
            derive_execution_id("training", "model-123")
        )

    def test_result_never_exceeds_64_characters(self):
        # UT: explicit length-bound check. A short prefix and a very
        # long, unsanitary first part must both stay within the Azure
        # Batch task ID cap the Batch adapter relies on.
        cases = [
            ("training", "model-123"),
            ("x", "y"),
            ("a" * 200,),
            ("a" * 200, "b" * 200),
            ("training/embedding job!!" * 10, "model-uid"),
        ]
        for parts in cases:
            result = derive_execution_id(*parts)
            assert len(result) <= self._BATCH_TASK_ID_MAX_LENGTH, parts
            assert self._EXECUTION_ID_RE.match(result)

    def test_long_prefix_is_truncated_not_the_hash(self):
        # The prefix must be what gets truncated when a part is long,
        # never the hash (that would weaken uniqueness guarantees).
        short = derive_execution_id("training", "model-123")
        long_ = derive_execution_id("training" * 20, "model-123")

        short_hash = short.rsplit("-", 1)[-1]
        long_hash = long_.rsplit("-", 1)[-1]

        # Different inputs -> different hash portions, but both hash
        # portions are the same fixed length regardless of prefix length.
        assert len(short_hash) == len(long_hash)
        assert short_hash != long_hash
        assert len(long_) <= self._BATCH_TASK_ID_MAX_LENGTH

    def test_derived_id_is_accepted_by_compute_job_spec(self):
        # Integration check: the id this helper produces must satisfy
        # ComputeJobSpec.executionId's own validator, not just an
        # independent regex copy in this test.
        from hastegeo.core.models.compute import (
            ComputeContainerRef,
            ComputeTags,
            ComputeWorkload,
        )

        execution_id = derive_execution_id("training", "model-123")
        spec = ComputeJobSpec(
            executionId=execution_id,
            workload=ComputeWorkload.TRAINING,
            container=ComputeContainerRef(
                imageReference="acr.example.io/train:v1.2.3"
            ),
            command="./run.sh",
            tags=ComputeTags(
                project="proj-1", workload=ComputeWorkload.TRAINING
            ),
        )

        assert spec.executionId == execution_id

    def test_derived_id_from_long_identity_fits_batch_task_id_maximum(self):
        # Integration check with a Batch-compatible maximum: even given
        # unrealistically long, real-world-shaped identity parts (e.g. a
        # long model name plus a UUID), the resulting executionId both
        # satisfies ComputeJobSpec's validator and never exceeds the 64
        # character limit the Azure Batch adapter's task ID is bound by.
        from hastegeo.core.models.compute import (
            ComputeContainerRef,
            ComputeTags,
            ComputeWorkload,
        )

        long_model_name = "Hurricane Harvey - Houston Damage Detection v2"
        model_uid = "550e8400-e29b-41d4-a716-446655440000"
        execution_id = derive_execution_id(
            "training", long_model_name, model_uid
        )

        assert len(execution_id) <= self._BATCH_TASK_ID_MAX_LENGTH

        spec = ComputeJobSpec(
            executionId=execution_id,
            workload=ComputeWorkload.TRAINING,
            container=ComputeContainerRef(
                imageReference="acr.example.io/train:v1.2.3"
            ),
            command="./run.sh",
            tags=ComputeTags(
                project="proj-1", workload=ComputeWorkload.TRAINING
            ),
        )

        assert spec.executionId == execution_id


class TestClearComputeHandles:
    """A request boundary must be able to drop a client-supplied runtime
    handle without touching anything else on the record."""

    def test_clears_a_single_record(self):
        job = TrainingJob(jobId="j", taskId="t", computeJob=_handle())

        clear_compute_handles(job)

        assert job.computeJob is None
        # Only the runtime handle is dropped; the record is untouched.
        assert job.jobId == "j"
        assert job.taskId == "t"

    def test_clears_every_record_in_a_list(self):
        jobs = [
            TrainingJob(taskId="a", computeJob=_handle()),
            TrainingJob(taskId="b", computeJob=_handle()),
        ]

        clear_compute_handles(jobs)

        assert [job.computeJob for job in jobs] == [None, None]

    def test_tolerates_missing_records(self):
        clear_compute_handles(None, [], [None])


class TestAuthoritativeJobHistory:
    """Job records are written by HASTE, so stored history wins over
    whatever a request body carries."""

    def test_stored_history_replaces_the_request_copy(self):
        stored = [TrainingJob(taskId="trn-1", computeJob=_handle())]
        forged = [
            TrainingJob(taskId="trn-1", computeJob=_handle()),
            TrainingJob(taskId="trn-forged", computeJob=_handle()),
        ]

        resolved = authoritative_job_history(forged, stored)

        assert [job.taskId for job in resolved] == ["trn-1"]
        # The stored handle survives; the forged extra record does not.
        assert resolved[0].computeJob is stored[0].computeJob

    def test_empty_stored_history_still_wins(self):
        forged = [TrainingJob(taskId="trn-forged", computeJob=_handle())]

        assert authoritative_job_history(forged, []) == []

    def test_falls_back_to_the_request_with_handles_cleared(self):
        requested = [TrainingJob(taskId="trn-1", computeJob=_handle())]

        resolved = authoritative_job_history(requested, None)

        assert [job.taskId for job in resolved] == ["trn-1"]
        assert resolved[0].computeJob is None

    def test_no_history_at_all(self):
        assert authoritative_job_history(None, None) == []


class TestSelectedBackendOf:
    def test_reads_the_backend_from_a_persisted_handle(self):
        job = TrainingJob(computeJob=_handle())

        assert selected_backend_of(job) == job.computeJob.selectedBackend.value

    def test_none_without_a_handle(self):
        assert selected_backend_of(TrainingJob(taskId="t")) is None
        assert selected_backend_of(None) is None


class TestPreserveWorkflowOwnedFields:
    """An *edit* may change what a user owns; everything the workflow
    writes is restored from what HASTE stored."""

    def test_restores_every_named_field(self):
        stored = TrainingJob(jobId="real-job", taskId="real-task")
        requested = TrainingJob(jobId="forged", taskId="forged")

        preserve_workflow_owned_fields(requested, stored, ("jobId", "taskId"))

        assert requested.jobId == "real-job"
        assert requested.taskId == "real-task"

    def test_leaves_unnamed_fields_alone(self):
        stored = TrainingJob(jobId="real-job", logs="stored logs")
        requested = TrainingJob(jobId="forged", logs="client logs")

        preserve_workflow_owned_fields(requested, stored, ("jobId",))

        assert requested.jobId == "real-job"
        assert requested.logs == "client logs"

    def test_restores_a_missing_value_too(self):
        # Clearing a stored value is as much a rewrite as forging one.
        stored = TrainingJob(jobId=None)
        requested = TrainingJob(jobId="forged")

        preserve_workflow_owned_fields(requested, stored, ("jobId",))

        assert requested.jobId is None

    def test_no_stored_record_is_a_no_op(self):
        requested = TrainingJob(jobId="client")

        preserve_workflow_owned_fields(requested, None, ("jobId",))

        assert requested.jobId == "client"

    def test_image_layer_field_list_covers_runtime_and_workflow_output(self):
        from hastegeo.core.models.projects import ImageLayer

        # Every listed field must exist on the model...
        for name in IMAGE_LAYER_WORKFLOW_OWNED_FIELDS:
            assert name in ImageLayer.model_fields, name
        # ...and the compute submission plus runtime status must be in it.
        for required in (
            "preprocessJob",
            "status",
            "statusMessage",
            "currentStep",
            "progressPct",
        ):
            assert required in IMAGE_LAYER_WORKFLOW_OWNED_FIELDS
        # Fields a user legitimately edits must NOT be preserved.
        for editable in (
            "name",
            "description",
            "preEventImageryUrls",
            "postEventImageryUrls",
            "clipBbox",
            "userBuildingFootprintsUrl",
            "computeBackend",
        ):
            assert editable not in IMAGE_LAYER_WORKFLOW_OWNED_FIELDS
