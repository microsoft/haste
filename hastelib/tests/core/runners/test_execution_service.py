# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ``ComputeExecutionService`` (validate, resolve, idempotent
submit, handle-based lifecycle dispatch).

See spec/features/aml-compute-backend/test-plan.md UT-009, UT-012..UT-015.
"""

import os
import unittest

from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    BackendConfigurationError,
    BackendUnavailableError,
    BatchProviderDetail,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeContainerRef,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeResources,
    ComputeTags,
    ComputeWorkload,
    LocalProviderDetail,
    SubmissionIndeterminateError,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.runners.execution_service import ComputeExecutionService
from hastegeo.core.runners.registry import RunnerRegistry


def _spec(execution_id="exec-1", backend_preference=ComputeBackend.AUTO):
    return ComputeJobSpec(
        executionId=execution_id,
        workload=ComputeWorkload.TRAINING,
        backendPreference=backend_preference,
        container=ComputeContainerRef(
            imageReference="acr.example.io/train@sha256:" + ("a1" * 32)
        ),
        command="./run.sh",
        tags=ComputeTags(project="proj-1", workload=ComputeWorkload.TRAINING),
    )


class FakeComputeRunner(ComputeRunner):
    """Minimal in-memory ``ComputeRunner`` used as a stand-in for a real,
    not-yet-migrated adapter.

    Deliberately duplicated here (rather than imported from
    ``test_registry.py``) so this test module has no cross-test-module
    dependency — a self-contained test fixture, not production code.
    """

    def __init__(self, config=None, backend=ComputeBackend.LOCAL):
        # Intentionally skip Config() construction so tests don't depend
        # on any environment/storage configuration being present.
        self.config = config
        self.backend = backend
        self.calls = []
        self.jobs = {}
        self.capacity_state = CapacityState.AVAILABLE

    def validate(self, spec: ComputeJobSpec) -> None:
        self.calls.append(("validate", spec.executionId))

    def submit(self, spec: ComputeJobSpec) -> ComputeJobHandle:
        self.calls.append(("submit", spec.executionId))
        existing = self.jobs.get(spec.executionId)
        if existing is not None:
            return existing

        discriminator = {
            ComputeBackend.AZURE_BATCH: "batch",
            ComputeBackend.AZURE_ML: "azure_ml",
            ComputeBackend.LOCAL: "local",
        }[self.backend]
        detail_kwargs = {}
        if discriminator == "batch":
            detail_kwargs["batch"] = BatchProviderDetail(
                jobId=f"job-{spec.executionId}", taskId=spec.executionId
            )
        elif discriminator == "azure_ml":
            detail_kwargs["azureMl"] = AzureMlProviderDetail(
                jobName=spec.executionId, workspace="ws"
            )
        else:
            detail_kwargs["local"] = LocalProviderDetail(
                executionDirectory=f"/tmp/{spec.executionId}"
            )

        handle = ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=self.backend,
            selectedBackend=self.backend,
            backendProfile="default",
            providerJobId=f"job-{spec.executionId}",
            providerTaskId=spec.executionId,
            targetId="target-1",
            outputUri="https://acct.blob.core.windows.net/c/out/",
            submittedAt="2026-01-01T00:00:00+00:00",
            routingReason="adapter-default",
            attempt=1,
            providerDetail=ComputeProviderDetail(
                discriminator=discriminator, **detail_kwargs
            ),
        )
        self.jobs[spec.executionId] = handle
        return handle

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        self.calls.append(("get_status", handle.executionId))
        return ComputeJobState.RUNNING

    def read_output(self, handle, relative_path, *, as_chunks=False):
        self.calls.append(("read_output", handle.executionId))
        return None

    def cancel(self, handle: ComputeJobHandle) -> None:
        self.calls.append(("cancel", handle.executionId))

    def finalize(self, handle: ComputeJobHandle) -> None:
        self.calls.append(("finalize", handle.executionId))

    def get_capacity(
        self, workload: ComputeWorkload, resources: ComputeResources
    ) -> CapacitySnapshot:
        self.calls.append(("get_capacity", workload.value))
        return CapacitySnapshot(
            backend=self.backend, workload=workload, state=self.capacity_state
        )


class RaisingOnceRunner(FakeComputeRunner):
    """Raises a given error on the first ``submit()`` call, then succeeds
    on subsequent calls (models a transient/indeterminate provider
    outcome)."""

    def __init__(self, error_factory, **kwargs):
        super().__init__(**kwargs)
        self._error_factory = error_factory
        self._raised = False

    def submit(self, spec):
        if not self._raised:
            self._raised = True
            raise self._error_factory()
        return super().submit(spec)


class AlwaysRaisingRunner(FakeComputeRunner):
    def __init__(self, error_factory, **kwargs):
        super().__init__(**kwargs)
        self._error_factory = error_factory

    def validate(self, spec):
        raise self._error_factory()


class RaisesOnCapacityRunner(FakeComputeRunner):
    """Raises a classified error from ``get_capacity()`` itself, modeling
    a candidate that is misconfigured/unavailable before routing even
    reaches ``validate()``/``submit()``."""

    def __init__(self, error_factory, **kwargs):
        super().__init__(**kwargs)
        self._error_factory = error_factory

    def get_capacity(self, workload, resources):
        raise self._error_factory()


class TestComputeExecutionServiceConstruction(unittest.TestCase):
    def test_rejects_negative_max_indeterminate_retries(self):
        with self.assertRaises(ValueError):
            ComputeExecutionService(max_indeterminate_retries=-1)

    def test_accepts_zero_max_indeterminate_retries(self):
        service = ComputeExecutionService(max_indeterminate_retries=0)
        self.assertEqual(service._max_indeterminate_retries, 0)


class TestExplicitSubmission(unittest.TestCase):
    """UT-009/UT-012: explicit backend routes directly (no router
    involvement) and surfaces a configuration error before any provider
    call, with no silent reroute."""

    def setUp(self):
        self.registry = RunnerRegistry()
        self.service = ComputeExecutionService(registry=self.registry)

    def test_explicit_backend_submits_without_router(self):
        fake = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: fake)

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        handle = self.service.submit(spec)

        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(handle.requestedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(handle.routingReason, "explicit")
        self.assertIn(("validate", spec.executionId), fake.calls)
        self.assertIn(("submit", spec.executionId), fake.calls)
        # get_capacity is router/auto-only; an explicit request must never
        # trigger it.
        self.assertNotIn(
            ("get_capacity", ComputeWorkload.TRAINING.value), fake.calls
        )

    def test_explicit_backend_not_registered_raises_configuration_error(self):
        spec = _spec(backend_preference=ComputeBackend.AZURE_ML)
        with self.assertRaises(BackendConfigurationError):
            self.service.submit(spec)

    def test_explicit_backend_disabled_raises_before_submit_no_reroute(self):
        def _raise():
            raise BackendConfigurationError("azure_ml disabled")

        broken = AlwaysRaisingRunner(_raise, backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: broken)

        spec = _spec(backend_preference=ComputeBackend.AZURE_ML)
        with self.assertRaises(BackendConfigurationError):
            self.service.submit(spec)
        # validate() raised; submit() must never have been attempted.
        self.assertNotIn(("submit", spec.executionId), broken.calls)


class TestAutoSubmission(unittest.TestCase):
    def setUp(self):
        self.registry = RunnerRegistry()
        self.service = ComputeExecutionService(registry=self.registry)

    def test_auto_with_no_candidates_raises_configuration_error(self):
        spec = _spec(backend_preference=ComputeBackend.AUTO)
        saved = {}
        for key in list(os.environ):
            if key.startswith("COMPUTE_AUTO_CANDIDATES_"):
                saved[key] = os.environ.pop(key)
        try:
            with self.assertRaises(BackendConfigurationError):
                self.service.submit(spec)
        finally:
            os.environ.update(saved)

    def test_auto_resolves_and_submits_to_selected_backend(self):
        batch = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        aml = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        handle = self.service.submit(
            spec,
            auto_candidates=[
                ComputeBackend.AZURE_BATCH,
                ComputeBackend.AZURE_ML,
            ],
        )

        self.assertEqual(handle.requestedBackend, ComputeBackend.AUTO)
        self.assertIn(
            handle.selectedBackend,
            (ComputeBackend.AZURE_BATCH, ComputeBackend.AZURE_ML),
        )
        self.assertTrue(handle.routingReason.startswith("auto:"))

        winner = (
            batch
            if handle.selectedBackend == ComputeBackend.AZURE_BATCH
            else aml
        )
        loser = aml if winner is batch else batch
        self.assertIn(("submit", spec.executionId), winner.calls)
        self.assertNotIn(("submit", spec.executionId), loser.calls)

    def test_auto_skips_unavailable_candidate_and_tries_next(self):
        batch = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        batch.capacity_state = CapacityState.UNAVAILABLE
        aml = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        handle = self.service.submit(
            spec,
            auto_candidates=[
                ComputeBackend.AZURE_BATCH,
                ComputeBackend.AZURE_ML,
            ],
        )
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)
        self.assertNotIn(("submit", spec.executionId), batch.calls)

    def test_auto_falls_back_when_validate_rejects_first_candidate(self):
        def _raise():
            raise BackendConfigurationError("batch misconfigured")

        batch = AlwaysRaisingRunner(_raise, backend=ComputeBackend.AZURE_BATCH)
        aml = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        handle = self.service.submit(
            spec,
            auto_candidates=[
                ComputeBackend.AZURE_BATCH,
                ComputeBackend.AZURE_ML,
            ],
            auto_weights={
                ComputeBackend.AZURE_BATCH: 1000,
                ComputeBackend.AZURE_ML: 1,
            },
        )
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)

    def test_auto_all_candidates_rejected_raises_backend_unavailable(self):
        def _raise():
            raise BackendUnavailableError("down")

        batch = AlwaysRaisingRunner(_raise, backend=ComputeBackend.AZURE_BATCH)
        aml = AlwaysRaisingRunner(_raise, backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        with self.assertRaises(BackendUnavailableError):
            self.service.submit(
                spec,
                auto_candidates=[
                    ComputeBackend.AZURE_BATCH,
                    ComputeBackend.AZURE_ML,
                ],
            )

    def test_auto_candidates_from_env_used_when_not_passed_explicitly(self):
        aml = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)
        os.environ["COMPUTE_AUTO_CANDIDATES_TRAINING"] = "azure_ml"
        try:
            spec = _spec(backend_preference=ComputeBackend.AUTO)
            handle = self.service.submit(spec)
            self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)
        finally:
            os.environ.pop("COMPUTE_AUTO_CANDIDATES_TRAINING", None)

    def test_auto_gathering_capacity_skips_candidate_whose_get_capacity_raises(
        self,
    ):
        """A misconfigured/unavailable candidate must be classified and
        excluded during capacity gathering, not abort routing for the
        other candidates (regression test for the dict-comprehension
        version that aborted the whole resolution)."""

        def _raise():
            raise BackendConfigurationError("azure_batch misconfigured")

        broken = RaisesOnCapacityRunner(
            _raise, backend=ComputeBackend.AZURE_BATCH
        )
        healthy = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: broken)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: healthy)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        handle = self.service.submit(
            spec,
            auto_candidates=[
                ComputeBackend.AZURE_BATCH,
                ComputeBackend.AZURE_ML,
            ],
        )
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)
        self.assertIn(("submit", spec.executionId), healthy.calls)

    def test_auto_gathering_capacity_skips_candidate_not_registered(self):
        """A candidate with no usable adapter at all (``registry.get``
        itself raising ``BackendConfigurationError``) must be classified
        and skipped too, not just a runner whose ``get_capacity`` raises.
        """

        def _broken_factory():
            raise BackendConfigurationError("azure_batch not configured")

        healthy = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: healthy)
        self.registry.register(ComputeBackend.AZURE_BATCH, _broken_factory)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        handle = self.service.submit(
            spec,
            auto_candidates=[
                ComputeBackend.AZURE_BATCH,
                ComputeBackend.AZURE_ML,
            ],
        )
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)

    def test_auto_all_candidates_fail_capacity_gathering_raises_backend_unavailable(
        self,
    ):
        def _raise():
            raise BackendConfigurationError("misconfigured")

        batch = RaisesOnCapacityRunner(
            _raise, backend=ComputeBackend.AZURE_BATCH
        )
        aml = RaisesOnCapacityRunner(_raise, backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: aml)

        spec = _spec(backend_preference=ComputeBackend.AUTO)
        with self.assertRaises(BackendUnavailableError):
            self.service.submit(
                spec,
                auto_candidates=[
                    ComputeBackend.AZURE_BATCH,
                    ComputeBackend.AZURE_ML,
                ],
            )


class TestIdempotentSubmissionAndReconciliation(unittest.TestCase):
    """UT-013/UT-014: indeterminate submission reconciles rather than
    creating a duplicate; two "workers" calling submit for the same
    executionId only ever produce one provider job."""

    def setUp(self):
        self.registry = RunnerRegistry()
        self.service = ComputeExecutionService(registry=self.registry)

    def test_indeterminate_then_success_reconciles_without_duplicate(self):
        def _raise():
            return SubmissionIndeterminateError("timeout")

        runner = RaisingOnceRunner(_raise, backend=ComputeBackend.AZURE_BATCH)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: runner)

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        handle = self.service.submit(spec)

        self.assertEqual(len(runner.jobs), 1)
        self.assertEqual(handle.providerJobId, f"job-{spec.executionId}")
        # F9: one indeterminate outcome then a successful submit() is two
        # actual attempts — the handle must reflect that, not whatever
        # the adapter itself stamped (FakeComputeRunner always sets 1).
        self.assertEqual(handle.attempt, 2)

    def test_single_call_submission_stamps_attempt_one(self):
        """F9 (preserving adapter value when only one call was needed):
        with no indeterminate outcome, exactly one submit() call is made,
        so the service-stamped attempt count is 1 — the same value
        FakeComputeRunner already puts on the handle itself."""
        runner = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: runner)

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        handle = self.service.submit(spec)

        self.assertEqual(handle.attempt, 1)

    def test_multiple_indeterminate_outcomes_stamp_the_actual_attempt_count(
        self,
    ):
        """More than one retry before success must be reflected exactly,
        not just capped at "more than one"."""

        class RaisesTwiceThenSucceedsRunner(FakeComputeRunner):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._raise_count = 0

            def submit(self, spec):
                if self._raise_count < 2:
                    self._raise_count += 1
                    raise SubmissionIndeterminateError("timeout")
                return super().submit(spec)

        runner = RaisesTwiceThenSucceedsRunner(
            backend=ComputeBackend.AZURE_BATCH
        )
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: runner)
        service = ComputeExecutionService(
            registry=self.registry, max_indeterminate_retries=2
        )

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        handle = service.submit(spec)

        self.assertEqual(handle.attempt, 3)

    def test_indeterminate_exhausts_retries_and_raises(self):
        def _raise():
            return SubmissionIndeterminateError("always times out")

        class AlwaysIndeterminateRunner(FakeComputeRunner):
            def submit(self, spec):
                raise _raise()

        runner = AlwaysIndeterminateRunner(backend=ComputeBackend.AZURE_BATCH)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: runner)
        service = ComputeExecutionService(
            registry=self.registry, max_indeterminate_retries=1
        )

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        with self.assertRaises(SubmissionIndeterminateError):
            service.submit(spec)

    def test_two_calls_with_same_execution_id_do_not_duplicate_provider_job(
        self,
    ):
        runner = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: runner)

        spec = _spec(backend_preference=ComputeBackend.AZURE_BATCH)
        first = self.service.submit(spec)
        second = self.service.submit(spec)

        self.assertEqual(first.providerJobId, second.providerJobId)
        self.assertEqual(len(runner.jobs), 1)
        submit_calls = [c for c in runner.calls if c[0] == "submit"]
        self.assertEqual(
            len(submit_calls), 2
        )  # both calls reach the adapter...
        # ...but the adapter's own get-or-create semantics mean only one
        # job was ever created.
        self.assertEqual(len(runner.jobs), 1)


class TestLifecycleDispatch(unittest.TestCase):
    """UT-015: lifecycle calls use the persisted handle's backend, never
    whatever the "current" default happens to be."""

    def setUp(self):
        self.registry = RunnerRegistry()
        self.service = ComputeExecutionService(registry=self.registry)
        self.batch = FakeComputeRunner(backend=ComputeBackend.AZURE_BATCH)
        self.aml = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_BATCH, lambda: self.batch)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: self.aml)

    def _handle_for(self, backend):
        spec = _spec(backend_preference=backend)
        return self.service.submit(spec)

    def test_get_status_dispatches_to_handles_backend(self):
        handle = self._handle_for(ComputeBackend.AZURE_ML)
        self.service.get_status(handle)
        self.assertIn(("get_status", handle.executionId), self.aml.calls)
        self.assertNotIn(("get_status", handle.executionId), self.batch.calls)

    def test_cancel_dispatches_to_handles_backend(self):
        handle = self._handle_for(ComputeBackend.AZURE_BATCH)
        self.service.cancel(handle)
        self.assertIn(("cancel", handle.executionId), self.batch.calls)
        self.assertNotIn(("cancel", handle.executionId), self.aml.calls)

    def test_finalize_and_read_output_dispatch_to_handles_backend(self):
        handle = self._handle_for(ComputeBackend.AZURE_ML)
        self.service.finalize(handle)
        self.service.read_output(handle, "progress.log")
        self.assertIn(("finalize", handle.executionId), self.aml.calls)
        self.assertIn(("read_output", handle.executionId), self.aml.calls)

    def test_config_change_mid_job_does_not_affect_lifecycle_routing(self):
        """Simulates a 'COMPUTE_BACKEND_DEFAULT changed mid-job' scenario:
        nothing in the service reads a "current default" for lifecycle
        dispatch, only the persisted handle."""
        handle = self._handle_for(ComputeBackend.AZURE_BATCH)
        os.environ["COMPUTE_BACKEND_DEFAULT"] = "azure_ml"
        try:
            self.service.get_status(handle)
        finally:
            os.environ.pop("COMPUTE_BACKEND_DEFAULT", None)
        self.assertIn(("get_status", handle.executionId), self.batch.calls)
        self.assertNotIn(("get_status", handle.executionId), self.aml.calls)


if __name__ == "__main__":
    unittest.main()
