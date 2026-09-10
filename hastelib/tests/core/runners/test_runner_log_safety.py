# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Observability/security regression tests: runner logs must never
interpolate a raw ``resource_files_for_upload`` dict, a full input/output
blob URL, or a signed query string — only safe correlation fields
(destination-relative paths, file keys, counts, executionId/backend/
profile/provider IDs/routing reason).

Covers ``UnifiedRunner.add_task``, ``LocalRunner``'s blob download helpers,
and ``ComputeExecutionService``'s auto-routing warning logs.
"""

import logging
import tempfile
import unittest
import warnings
from unittest.mock import MagicMock, patch

from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    BackendConfigurationError,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeContainerRef,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeTags,
    ComputeWorkload,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.runners.execution_service import ComputeExecutionService
from hastegeo.core.runners.local import LocalRunner
from hastegeo.core.runners.registry import RunnerRegistry
from hastegeo.core.runners.unified_runner import UnifiedRunner

from hastelib.tests.core.runners.test_local_compute_runner import (
    _runner as local_runner,
)

# A representative "signed URL" shape: any of these substrings leaking
# into a log line is a failure, regardless of which safety fix caught it.
_SIGNED_QUERY_SECRET = "TOPSECRETSIGNATURE"  # pragma: allowlist secret
_SIGNED_URL = (
    "https://acct.blob.core.windows.net/c/f.tif"
    f"?sv=2020-01-01&se=2030-01-01&sig={_SIGNED_QUERY_SECRET}"
)


def _spec(**overrides):
    kwargs = dict(
        executionId="exec-1",
        workload=ComputeWorkload.TRAINING,
        backendPreference=ComputeBackend.AUTO,
        container=ComputeContainerRef(
            imageReference="acr.example.io/train@sha256:" + ("a1" * 32)
        ),
        command="python run.py",
        tags=ComputeTags(project="p1", workload=ComputeWorkload.TRAINING),
    )
    kwargs.update(overrides)
    return ComputeJobSpec(**kwargs)


class _AlwaysRaisingRunner(ComputeRunner):
    """A ComputeRunner whose validate() raises a BackendConfigurationError
    carrying a signed-URL-shaped message — models an adapter that (bug or
    not) let a URL leak into a typed error's text, so the execution
    service's own logging must not propagate it further."""

    def __init__(self, config=None, backend=ComputeBackend.AZURE_BATCH):
        self.config = config
        self.backend = backend

    def validate(self, spec):
        raise BackendConfigurationError(f"rejected input URI ({_SIGNED_URL})")

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
        return CapacitySnapshot(
            backend=self.backend,
            workload=workload,
            state=CapacityState.AVAILABLE,
        )


class _HealthyRunner(ComputeRunner):
    def __init__(self, config=None, backend=ComputeBackend.AZURE_ML):
        self.config = config
        self.backend = backend

    def validate(self, spec):
        return None

    def submit(self, spec):
        return ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=self.backend,
            selectedBackend=self.backend,
            backendProfile="default",
            providerJobId="job-1",
            providerTaskId=spec.executionId,
            targetId="target-1",
            outputUri="https://acct.blob.core.windows.net/c/out/",
            submittedAt="2026-01-01T00:00:00+00:00",
            routingReason="adapter-default",
            attempt=1,
            providerDetail=ComputeProviderDetail(
                discriminator="azure_ml",
                azureMl=AzureMlProviderDetail(
                    jobName=spec.executionId, workspace="ws"
                ),
            ),
        )

    def get_status(self, handle):
        return ComputeJobState.RUNNING

    def read_output(self, handle, relative_path, *, as_chunks=False):
        return None

    def cancel(self, handle):
        return None

    def finalize(self, handle):
        return None

    def get_capacity(self, workload, resources):
        return CapacitySnapshot(
            backend=self.backend,
            workload=workload,
            state=CapacityState.AVAILABLE,
        )


class TestUnifiedRunnerLoggingSafety(unittest.TestCase):
    @patch("hastegeo.core.runners.unified_runner.importlib.import_module")
    def test_deprecation_warning_names_qualified_replacement(
        self, import_module
    ):
        module = MagicMock()
        module.AzureBatchRunner = MagicMock()
        import_module.return_value = module

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            UnifiedRunner("azure_batch", config=MagicMock())

        self.assertEqual(len(caught), 1)
        self.assertIn(
            "hastegeo.core.runners.execution_service."
            "ComputeExecutionService, which targets",
            str(caught[0].message),
        )

    def test_add_task_never_logs_raw_resource_dict_or_signed_url(self):
        runner = UnifiedRunner.__new__(UnifiedRunner)
        runner.runner = MagicMock()
        runner.runner.add_task.return_value = ("job-1", "task-1")

        resource_files = {
            "in/f.tif": {"http_url": _SIGNED_URL, "file_path": "in/f.tif"}
        }

        with self.assertLogs(
            "hastegeo.core.runners.unified_runner", level="INFO"
        ) as cm:
            runner.add_task(
                "job-1",
                "task-1",
                resource_files_for_upload=resource_files,
            )

        combined = "\n".join(cm.output)
        self.assertNotIn(_SIGNED_URL, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)
        # Safe correlation fields (destination-relative path, count,
        # job/task id) must still be present.
        self.assertIn("in/f.tif", combined)
        self.assertIn("job_id=job-1", combined)
        self.assertIn("task_id=task-1", combined)


class TestLocalRunnerBlobLoggingSafety(unittest.TestCase):
    def _runner_with_logger(self, logger_name):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runner = local_runner(directory.name)
        runner.logger = logging.getLogger(logger_name)
        runner.blob_client.credential = None
        runner.blob_client.account_name = "acct"
        runner.blob_client.url = "https://acct.blob.core.windows.net/"
        return runner

    def _submit(self, runner: LocalRunner, url: str):
        return runner.add_task(
            job_id="job",
            task_id="task",
            image_name="training",
            command="python run.py",
            output_container_url="data",
            resource_files_for_upload={
                "input": {"http_url": url, "file_path": "in/f.tif"}
            },
        )

    def test_accepted_receipt_never_stores_or_logs_signed_url(self):
        logger_name = "test.local.blob_candidates.1"
        runner = self._runner_with_logger(logger_name)
        with self.assertNoLogs(logger_name, level="DEBUG"):
            self._submit(runner, _SIGNED_URL.replace("/c/", "/data/"))
        receipt = next(runner.receipts.root.glob("*.json")).read_text()
        self.assertNotIn(_SIGNED_URL, receipt)
        self.assertNotIn(_SIGNED_QUERY_SECRET, receipt)

    def test_unsafe_path_error_never_echoes_the_url(self):
        logger_name = "test.local.blob_candidates.2"
        runner = self._runner_with_logger(logger_name)
        malicious_url = (
            "https://acct.blob.core.windows.net/data/../secret"
            f"?sv=2020&sig={_SIGNED_QUERY_SECRET}"
        )

        with self.assertNoLogs(logger_name, level="DEBUG"):
            with self.assertRaises(ValueError) as error:
                self._submit(runner, malicious_url)
        self.assertNotIn(malicious_url, str(error.exception))
        self.assertNotIn(_SIGNED_QUERY_SECRET, str(error.exception))
        self.assertIn("safe relative paths", str(error.exception))

    def test_download_resource_files_failure_never_logs_the_source_url(
        self,
    ):
        logger_name = "test.local.download_resource_files"
        runner = self._runner_with_logger(logger_name)
        identity = self._submit(runner, _SIGNED_URL.replace("/c/", "/data/"))
        with patch.object(
            runner.blob_client,
            "get_blob_client",
            side_effect=OSError(f"download failed: {_SIGNED_URL}"),
        ):
            with self.assertLogs(logger_name, level="INFO") as cm:
                runner.reconcile_task(*identity)

        combined = "\n".join(cm.output)
        self.assertNotIn(_SIGNED_URL, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)
        # The destination-relative path (file key) is still safe to log.
        self.assertIn("in/f.tif", combined)
        self.assertEqual(runner.get_task_status(*identity), "Failed")


class TestExecutionServiceLoggingSafety(unittest.TestCase):
    def test_auto_routing_warning_redacts_leaked_signed_url_but_keeps_correlation(
        self,
    ):
        """Defense-in-depth: even if an adapter's typed error message
        somehow embeds a signed URL, the execution service's own routing
        log must not propagate it — while still surfacing the safe
        backend/routing correlation fields the routing decision needs."""
        registry = RunnerRegistry()
        broken = _AlwaysRaisingRunner(backend=ComputeBackend.AZURE_BATCH)
        healthy = _HealthyRunner(backend=ComputeBackend.AZURE_ML)
        registry.register(ComputeBackend.AZURE_BATCH, lambda: broken)
        registry.register(ComputeBackend.AZURE_ML, lambda: healthy)
        service = ComputeExecutionService(registry=registry)

        spec = _spec(backendPreference=ComputeBackend.AUTO)

        with self.assertLogs(
            "hastegeo.core.runners.execution_service", level="WARNING"
        ) as cm:
            handle = service.submit(
                spec,
                auto_candidates=[
                    ComputeBackend.AZURE_BATCH,
                    ComputeBackend.AZURE_ML,
                ],
                # Force the deterministic rendezvous ranking to try the
                # broken candidate first, so its leaking error message is
                # guaranteed to reach the routing warning log below.
                auto_weights={
                    ComputeBackend.AZURE_BATCH: 1000,
                    ComputeBackend.AZURE_ML: 1,
                },
            )

        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)
        combined = "\n".join(cm.output)
        self.assertNotIn(_SIGNED_URL, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)
        self.assertIn("<redacted>", combined)
        # Safe correlation fields: which backend was rejected, and that
        # routing moved on to try the next candidate.
        self.assertIn(ComputeBackend.AZURE_BATCH.value, combined)
        self.assertIn("trying next candidate", combined)


if __name__ == "__main__":
    unittest.main()
