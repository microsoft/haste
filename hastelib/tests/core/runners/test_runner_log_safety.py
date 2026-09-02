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
from pathlib import Path
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
        runner = LocalRunner.__new__(LocalRunner)
        runner.logger = logging.getLogger(logger_name)
        runner.blob_client = MagicMock()
        runner.blob_client.credential = None
        runner.blob_client.account_name = None
        return runner

    def test_build_blob_client_candidates_never_logs_signed_url(self):
        logger_name = "test.local.blob_candidates.1"
        runner = self._runner_with_logger(logger_name)

        with patch(
            "hastegeo.core.runners.local.BlobClient.from_blob_url",
            side_effect=ValueError(f"could not parse {_SIGNED_URL}"),
        ):
            with self.assertLogs(logger_name, level="DEBUG") as cm:
                runner._build_blob_client_candidates(_SIGNED_URL)

        combined = "\n".join(cm.output)
        self.assertNotIn(_SIGNED_URL, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)

    def test_unsafe_path_segment_warning_never_logs_the_url(self):
        logger_name = "test.local.blob_candidates.2"
        runner = self._runner_with_logger(logger_name)
        malicious_url = (
            "https://acct.blob.core.windows.net/c/../secret"
            f"?sv=2020&sig={_SIGNED_QUERY_SECRET}"
        )

        with self.assertLogs(logger_name, level="WARNING") as cm:
            runner._build_blob_client_candidates(malicious_url)

        combined = "\n".join(cm.output)
        self.assertNotIn(malicious_url, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)
        self.assertIn("unsafe path segments", combined)

    def test_download_resource_files_failure_never_logs_the_source_url(
        self,
    ):
        logger_name = "test.local.download_resource_files"
        runner = self._runner_with_logger(logger_name)
        resource_files = {
            "in/f.tif": {"http_url": _SIGNED_URL, "file_path": "in/f.tif"}
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                runner, "_build_blob_client_candidates", return_value=[]
            ):
                with self.assertLogs(logger_name, level="INFO") as cm:
                    runner._download_resource_files(Path(tmp), resource_files)

        combined = "\n".join(cm.output)
        self.assertNotIn(_SIGNED_URL, combined)
        self.assertNotIn(_SIGNED_QUERY_SECRET, combined)
        # The destination-relative path (file key) is still safe to log.
        self.assertIn("in/f.tif", combined)


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
