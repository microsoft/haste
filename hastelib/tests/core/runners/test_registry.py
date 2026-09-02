# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ``RunnerRegistry`` (construct/cache adapters by backend +
profile, lazy default-import fallback, no faked adapter migrations).
"""

import unittest

from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    BackendConfigurationError,
    BatchProviderDetail,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeResources,
    ComputeWorkload,
    LocalProviderDetail,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.runners.registry import RunnerRegistry


class FakeComputeRunner(ComputeRunner):
    """Minimal in-memory ``ComputeRunner`` used across the new runner test
    suites (registry/router/execution-service) as a stand-in for a real,
    not-yet-migrated adapter."""

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


class NotAComputeRunner:
    """Deliberately does not implement ``ComputeRunner`` — used to prove the
    registry refuses to hand out a non-conformant adapter."""

    def __init__(self, config=None):
        self.config = config


class RaisingConstructorRunner(ComputeRunner):
    """Raises during ``__init__`` — used to prove the registry classifies
    *any* adapter construction failure (not just import failures), which
    matters for e.g. ``LocalRunner`` eagerly connecting to Docker in its
    own ``__init__``."""

    def __init__(self, config=None):
        raise RuntimeError("simulated adapter construction failure")

    # Concrete no-op implementations so this class is instantiable at all
    # (ABC would otherwise reject it before __init__ even runs, which
    # would test the wrong failure mode).
    def validate(self, spec):
        raise NotImplementedError

    def submit(self, spec):
        raise NotImplementedError

    def get_status(self, handle):
        raise NotImplementedError

    def read_output(self, handle, relative_path, *, as_chunks=False):
        raise NotImplementedError

    def cancel(self, handle):
        raise NotImplementedError

    def finalize(self, handle):
        raise NotImplementedError

    def get_capacity(self, workload, resources):
        raise NotImplementedError


class TestRunnerRegistryRegisterAndGet(unittest.TestCase):
    def setUp(self):
        self.registry = RunnerRegistry()

    def test_get_returns_registered_factory_instance(self):
        fake = FakeComputeRunner(backend=ComputeBackend.LOCAL)
        self.registry.register(ComputeBackend.LOCAL, lambda: fake)
        self.assertIs(self.registry.get(ComputeBackend.LOCAL), fake)

    def test_get_caches_instance_across_calls(self):
        build_count = {"n": 0}

        def factory():
            build_count["n"] += 1
            return FakeComputeRunner(backend=ComputeBackend.LOCAL)

        self.registry.register(ComputeBackend.LOCAL, factory)
        first = self.registry.get(ComputeBackend.LOCAL)
        second = self.registry.get(ComputeBackend.LOCAL)
        self.assertIs(first, second)
        self.assertEqual(build_count["n"], 1)

    def test_distinct_profiles_get_distinct_instances(self):
        self.registry.register(
            ComputeBackend.LOCAL,
            lambda: FakeComputeRunner(backend=ComputeBackend.LOCAL),
            profile="a",
        )
        self.registry.register(
            ComputeBackend.LOCAL,
            lambda: FakeComputeRunner(backend=ComputeBackend.LOCAL),
            profile="b",
        )
        runner_a = self.registry.get(ComputeBackend.LOCAL, profile="a")
        runner_b = self.registry.get(ComputeBackend.LOCAL, profile="b")
        self.assertIsNot(runner_a, runner_b)

    def test_register_overwrite_drops_cached_instance(self):
        old = FakeComputeRunner(backend=ComputeBackend.LOCAL)
        self.registry.register(ComputeBackend.LOCAL, lambda: old)
        self.assertIs(self.registry.get(ComputeBackend.LOCAL), old)

        new = FakeComputeRunner(backend=ComputeBackend.LOCAL)
        self.registry.register(ComputeBackend.LOCAL, lambda: new)
        self.assertIs(self.registry.get(ComputeBackend.LOCAL), new)

    def test_get_rejects_auto(self):
        with self.assertRaises(BackendConfigurationError):
            self.registry.get(ComputeBackend.AUTO)

    def test_register_rejects_auto(self):
        with self.assertRaises(ValueError):
            self.registry.register(ComputeBackend.AUTO, lambda: None)

    def test_get_rejects_non_conformant_adapter(self):
        self.registry.register(
            ComputeBackend.LOCAL, lambda: NotAComputeRunner()
        )
        with self.assertRaises(BackendConfigurationError):
            self.registry.get(ComputeBackend.LOCAL)

    def test_get_classifies_a_constructor_failure(self):
        self.registry.register(ComputeBackend.LOCAL, RaisingConstructorRunner)
        with self.assertRaises(BackendConfigurationError):
            self.registry.get(ComputeBackend.LOCAL)

    def test_clear_drops_registrations_and_falls_back_to_default(self):
        # azure_ml is now implemented (plan.md Phase 7), so after clearing
        # an explicit registration, get() must fall through to the real
        # default ``AzureMLRunner`` adapter — a distinct instance from the
        # cleared fake — rather than returning the fake or some other
        # stale state.
        from hastegeo.core.runners.azure_ml import AzureMLRunner

        fake = FakeComputeRunner(backend=ComputeBackend.AZURE_ML)
        self.registry.register(ComputeBackend.AZURE_ML, lambda: fake)
        self.assertIs(self.registry.get(ComputeBackend.AZURE_ML), fake)

        self.registry.clear()

        runner = self.registry.get(ComputeBackend.AZURE_ML)
        self.assertIsNot(runner, fake)
        self.assertIsInstance(runner, AzureMLRunner)


class TestRunnerRegistryDefaultLazyImport(unittest.TestCase):
    """``_ADAPTER_MODULE_MAP`` lists ``azure_batch``/``local``/``azure_ml``
    (all migrated to/implementing ``ComputeRunner`` — plan.md Phases 4 &
    7). Every outcome below must be a real, conformant ``ComputeRunner``
    instance or a classified ``BackendConfigurationError`` — never an
    unclassified exception."""

    def setUp(self):
        self.registry = RunnerRegistry()

    def test_azure_ml_is_available_via_default_lazy_import(self):
        # AzureMLRunner.__init__ never makes a network call or eagerly
        # validates AML_* settings (that's validate()'s job, called before
        # any provider call) — construction alone always succeeds,
        # mirroring AzureBatchRunner's own lazy-init contract below.
        from hastegeo.core.runners.azure_ml import AzureMLRunner

        runner = self.registry.get(ComputeBackend.AZURE_ML)
        self.assertIsInstance(runner, ComputeRunner)
        self.assertIsInstance(runner, AzureMLRunner)
        # Cached: a second get() returns the same instance.
        self.assertIs(self.registry.get(ComputeBackend.AZURE_ML), runner)

    def test_azure_batch_is_available_via_default_lazy_import(self):
        # AzureBatchRunner.__init__ never makes a network call (Config()
        # always returns placeholder values without erroring in dev/test),
        # so this is deterministic across environments.
        from hastegeo.core.runners.azure_batch import AzureBatchRunner

        runner = self.registry.get(ComputeBackend.AZURE_BATCH)
        self.assertIsInstance(runner, ComputeRunner)
        self.assertIsInstance(runner, AzureBatchRunner)
        # Cached: a second get() returns the same instance.
        self.assertIs(self.registry.get(ComputeBackend.AZURE_BATCH), runner)

    def test_local_default_lazy_import_result_is_classified_or_conformant(
        self,
    ):
        # LocalRunner.__init__ eagerly connects to Docker, so whether this
        # succeeds depends on the environment (daemon availability). Either
        # outcome is acceptable; an unclassified exception is not.
        try:
            runner = self.registry.get(ComputeBackend.LOCAL)
        except BackendConfigurationError:
            return
        self.assertIsInstance(runner, ComputeRunner)


if __name__ == "__main__":
    unittest.main()
