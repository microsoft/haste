# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the Azure Machine Learning ``ComputeRunner`` adapter
(``hastegeo.core.runners.azure_ml.AzureMLRunner``).

Mocked against ``MLClient``/``azure.core.exceptions`` — no live AML calls.
Constructs instances via ``AzureMLRunner.__new__`` (bypassing ``__init__``,
which would otherwise construct a real ``Config()``), the same pattern used
for ``AzureBatchRunner``/``LocalRunner`` in the sibling
``test_azure_batch_compute_runner.py``/``test_local_compute_runner.py``.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    BackendConfigurationError,
    BackendUnavailableError,
    CapacityState,
    ComputeBackend,
    ComputeContainerRef,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeOutput,
    ComputeProviderDetail,
    ComputeResources,
    ComputeTags,
    ComputeWorkload,
    InputDeliveryMode,
    InputKind,
    JobCancellationError,
    JobNotFoundError,
    OutputNotAvailableError,
    OutputPersistenceMode,
    SubmissionIndeterminateError,
)
from hastegeo.core.runners.azure_ml import (
    AmbiguousOutputMatchError,
    AzureMLRunner,
    UnmappedAmlJobStatusError,
    _build_bootstrap_command,
    _normalize_quoted_command,
    _pattern_static_directory,
    _resolve_output_layout,
    _sanitized_tags,
)
from hastegeo.core.runners.base import ComputeRunner


def _aml_config(**overrides):
    base = {
        "mode": "Existing",
        "subscription_id": "sub-1",
        "resource_group": "rg-1",
        "workspace_name": "ws-1",
        "datastore_name": "haste-datastore",
        "compute_by_workload": {
            ComputeWorkload.TRAINING: "gpu-cluster",
            ComputeWorkload.INFERENCE: "gpu-cluster",
            ComputeWorkload.EMBEDDING: "gpu-cluster",
            ComputeWorkload.IMAGERY_PREPARATION: "cpu-cluster",
            ComputeWorkload.ARTIFACT_PACKAGING: "cpu-cluster",
        },
        "environment_by_workload": {
            ComputeWorkload.TRAINING: "azureml:train-env:3",
            ComputeWorkload.INFERENCE: "azureml:train-env:3",
            ComputeWorkload.EMBEDDING: "azureml:train-env:3",
            ComputeWorkload.IMAGERY_PREPARATION: "azureml:imageryprep-env:2",
            ComputeWorkload.ARTIFACT_PACKAGING: "azureml:imageryprep-env:2",
        },
        "identity_mode": "user",
        "managed_identity_id": None,
        "experiment_prefix": "haste",
        "submission_timeout_seconds": 5,
    }
    base.update(overrides)
    return base


def _runner(client=None, **aml_overrides):
    runner = AzureMLRunner.__new__(AzureMLRunner)
    runner.config = MagicMock(spec=Config)
    runner.aml_config = _aml_config(**aml_overrides)
    runner.logger = MagicMock()
    runner._client = client if client is not None else MagicMock()
    runner._client_lock = threading.Lock()
    runner._credential_instance = MagicMock()
    return runner


def _spec(**overrides):
    kwargs = dict(
        executionId="exec-1",
        workload=ComputeWorkload.TRAINING,
        backendPreference=ComputeBackend.AZURE_ML,
        container=ComputeContainerRef(
            imageReference="acr.example.io/train:v1"
        ),
        command="python run.py",
        inputs=[
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            )
        ],
        outputs=[
            ComputeOutput(
                name="out",
                sourceRelativePattern="outputs/*.tif",
                destinationUri=(
                    "https://a.blob.core.windows.net/data/proj/task-1/"
                ),
            )
        ],
        tags=ComputeTags(project="p1", workload=ComputeWorkload.TRAINING),
    )
    kwargs.update(overrides)
    return ComputeJobSpec(**kwargs)


def _handle(**overrides):
    kwargs = dict(
        executionId="exec-1",
        requestedBackend=ComputeBackend.AZURE_ML,
        selectedBackend=ComputeBackend.AZURE_ML,
        backendProfile="default",
        providerJobId="haste-exec-1",
        providerTaskId=None,
        targetId="gpu-cluster",
        outputUri="https://a.blob.core.windows.net/data/proj/task-1/",
        submittedAt="2026-01-01T00:00:00+00:00",
        routingReason="adapter-default",
        attempt=1,
        providerDetail=ComputeProviderDetail(
            discriminator="azure_ml",
            azureMl=AzureMlProviderDetail(
                jobName="haste-exec-1", workspace="ws-1"
            ),
        ),
    )
    kwargs.update(overrides)
    return ComputeJobHandle(**kwargs)


def _http_error(status_code, message="error"):
    exc = HttpResponseError(message=message)
    exc.status_code = status_code
    return exc


def _workload_command_line(command: str) -> str:
    """Return the workload's own normalized shell chain from a generated
    bootstrap script.

    The workload command is wrapped in a ``{ ...; }`` group with
    stdout/stderr redirected to durable ``stdout.txt``/``stderr.txt``
    files under ``HASTE_OUTPUT_ROOT`` (design.md#security's AML
    ENTRYPOINT-bypass hardening, provider-parity diagnostics capture),
    and is no longer the script's final line either — it is followed by
    exit-code capture and finalization (``chmod``) footer lines — so
    tests locate it by position relative to the ``set +e`` line that
    immediately precedes it, then strip the surrounding wrapper, rather
    than assuming it is a bare final line.
    """
    lines = command.splitlines()
    wrapped = lines[lines.index("set +e") + 1]
    prefix = "{ "
    suffix_marker = '; } > "$HASTE_OUTPUT_ROOT/'
    assert wrapped.startswith(prefix) and suffix_marker in wrapped, wrapped
    return wrapped[len(prefix) : wrapped.index(suffix_marker)]


def _output(
    pattern: str,
    *,
    name: str = "out",
    destination: str = "https://a.blob.core.windows.net/data/proj/task-1/",
    persistence_mode=None,
) -> ComputeOutput:
    kwargs = dict(
        name=name,
        sourceRelativePattern=pattern,
        destinationUri=destination,
    )
    if persistence_mode is not None:
        kwargs["persistenceMode"] = persistence_mode
    return ComputeOutput(**kwargs)


def _root_outputs() -> list:
    """A single root-pattern output (``**/*``) — the default ``outputs``
    fixture for tests that don't specifically exercise output-layout
    behavior, preserving the pre-existing "HASTE_JOB_WORKDIR binds
    directly to the durable output root" bootstrap shape they assert on.
    """
    return [_output("**/*")]


def _job(name="haste-exec-1", status="Completed", execution_id="exec-1"):
    job = MagicMock()
    job.name = name
    job.status = status
    job.tags = {"executionId": execution_id} if execution_id else {}
    return job


class TestIsComputeRunner(unittest.TestCase):
    def test_is_instance_of_compute_runner(self):
        self.assertTrue(issubclass(AzureMLRunner, ComputeRunner))


class TestLazyImport(unittest.TestCase):
    def test_lazy_import_of_missing_module_raises_configuration_error(self):
        from hastegeo.core.runners.azure_ml import _lazy_import

        with self.assertRaises(BackendConfigurationError):
            _lazy_import("hastegeo.does.not.exist", "Nothing")

    def test_module_import_does_not_import_azure_ai_ml(self):
        # Regression test for the lazy-SDK-import contract
        # (design.md#configuration): importing this module alone must
        # never pull in azure-ai-ml. Run in a fresh subprocess so no other
        # test's prior import of azure.ai.ml can mask a violation.
        script = (
            "import sys\n"
            "import hastegeo.core.runners.azure_ml as m\n"
            "assert 'azure.ai.ml' not in sys.modules, "
            "'azure.ai.ml imported at module scope'\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode, 0, msg=result.stdout + result.stderr
        )
        self.assertIn("OK", result.stdout)

    def test_lazy_ml_exceptions_returns_job_and_validation_exception(self):
        from azure.ai.ml.exceptions import JobException, ValidationException
        from hastegeo.core.runners.azure_ml import _lazy_ml_exceptions

        job_exc, validation_exc = _lazy_ml_exceptions()
        self.assertIs(job_exc, JobException)
        self.assertIs(validation_exc, ValidationException)


class TestValidate(unittest.TestCase):
    def test_raises_when_mode_disabled(self):
        runner = _runner(mode="Disabled")
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_accepts_create_mode(self):
        # 'Create' is accepted for parity with Batch's mode vocabulary —
        # this adapter does not distinguish it from 'Existing' and does
        # not provision anything for either; both require the same
        # already-existing resource identifiers.
        runner = _runner(mode="Create")
        runner.validate(_spec())  # must not raise

    def test_raises_when_mode_is_unrecognized(self):
        runner = _runner(mode="Bogus")
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_raises_when_required_settings_missing(self):
        runner = _runner(subscription_id=None)
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_raises_when_identity_mode_invalid(self):
        runner = _runner(identity_mode="bogus")
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_raises_when_managed_identity_missing_resource_id(self):
        runner = _runner(identity_mode="managed", managed_identity_id=None)
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_passes_when_managed_identity_has_resource_id(self):
        runner = _runner(
            identity_mode="managed",
            managed_identity_id="/subscriptions/x/.../identity",
        )
        runner.validate(_spec())  # must not raise

    def test_passes_with_user_identity_mode(self):
        runner = _runner(identity_mode="user")
        runner.validate(_spec())  # must not raise

    def test_raises_when_no_outputs(self):
        runner = _runner()
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec(outputs=[]))

    def test_raises_when_outputs_span_multiple_containers(self):
        runner = _runner()
        spec = _spec(
            outputs=[
                ComputeOutput(
                    name="a",
                    sourceRelativePattern="a/*.tif",
                    destinationUri=(
                        "https://a.blob.core.windows.net/data/p/t/"
                    ),
                ),
                ComputeOutput(
                    name="b",
                    sourceRelativePattern="b/*.tif",
                    destinationUri=(
                        "https://a.blob.core.windows.net/other/p/t/"
                    ),
                ),
            ]
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(spec)

    def test_raises_when_no_compute_configured_for_workload(self):
        runner = _runner(
            compute_by_workload={
                ComputeWorkload.TRAINING: None,
                ComputeWorkload.INFERENCE: None,
                ComputeWorkload.EMBEDDING: None,
                ComputeWorkload.IMAGERY_PREPARATION: None,
                ComputeWorkload.ARTIFACT_PACKAGING: None,
            }
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_target_override_bypasses_configured_compute_lookup(self):
        runner = _runner(
            compute_by_workload={
                ComputeWorkload.TRAINING: None,
                ComputeWorkload.INFERENCE: None,
                ComputeWorkload.EMBEDDING: None,
                ComputeWorkload.IMAGERY_PREPARATION: None,
                ComputeWorkload.ARTIFACT_PACKAGING: None,
            }
        )
        spec = _spec(
            resources=ComputeResources(targetOverride="custom-cluster")
        )
        runner.validate(spec)  # must not raise

    def test_raises_when_no_environment_configured_for_workload(self):
        runner = _runner(
            environment_by_workload={w: None for w in ComputeWorkload}
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_passes_when_spec_supplies_explicit_environment_reference(self):
        # An explicit container.environmentReference always takes
        # precedence, even with no AML_ENVIRONMENT_* setting configured.
        runner = _runner(
            environment_by_workload={w: None for w in ComputeWorkload}
        )
        spec = _spec(
            container=ComputeContainerRef(
                imageReference="acr.example.io/train:v1",
                environmentReference="azureml:explicit-env:9",
            )
        )
        runner.validate(spec)  # must not raise

    def test_passes_with_valid_config(self):
        runner = _runner()
        runner.validate(_spec())  # must not raise


class TestJobNaming(unittest.TestCase):
    def test_job_name_uses_experiment_prefix_and_sanitizes_execution_id(self):
        runner = _runner(experiment_prefix="haste")
        name = runner._job_name_for("exec.1_ABC-2")
        # '.' is not in the allowed job-name character set, so it is
        # replaced with '-'; everything else is lowercased unchanged.
        self.assertEqual(name, "haste-exec-1_abc-2")
        self.assertNotIn(".", name)

    def test_job_name_sanitizes_disallowed_characters(self):
        runner = _runner()
        name = runner._job_name_for("exec/weird*name")
        self.assertNotIn("/", name)
        self.assertNotIn("*", name)

    def test_job_name_is_bounded_length(self):
        runner = _runner()
        name = runner._job_name_for("x" * 500)
        self.assertLessEqual(len(name), 200)

    def test_experiment_name_includes_workload(self):
        runner = _runner(experiment_prefix="haste")
        self.assertEqual(
            runner._experiment_name_for(ComputeWorkload.TRAINING),
            "haste-training",
        )


class TestIdentity(unittest.TestCase):
    def test_managed_mode_returns_managed_identity_with_resource_id(self):
        from azure.ai.ml.entities import ManagedIdentityConfiguration

        runner = _runner(
            identity_mode="managed",
            managed_identity_id="/subscriptions/x/.../identity",
        )
        identity = runner._identity()
        self.assertIsInstance(identity, ManagedIdentityConfiguration)
        self.assertEqual(identity.resource_id, "/subscriptions/x/.../identity")

    def test_user_mode_returns_user_identity_configuration(self):
        from azure.ai.ml.entities import UserIdentityConfiguration

        runner = _runner(identity_mode="user")
        self.assertIsInstance(runner._identity(), UserIdentityConfiguration)

    def test_invalid_identity_mode_raises_configuration_error(self):
        runner = _runner(identity_mode="bogus")
        with self.assertRaises(BackendConfigurationError):
            runner._identity()


class TestEnvironmentReferenceResolution(unittest.TestCase):
    def test_prefers_explicit_spec_container_environment_reference(self):
        runner = _runner(
            environment_by_workload={w: None for w in ComputeWorkload}
        )
        spec = _spec(
            container=ComputeContainerRef(
                imageReference="acr.example.io/train:v1",
                environmentReference="azureml:explicit-env:9",
            )
        )
        self.assertEqual(
            runner._environment_reference_for(spec),
            "azureml:explicit-env:9",
        )

    def test_falls_back_to_training_family_setting(self):
        runner = _runner()
        for workload in (
            ComputeWorkload.TRAINING,
            ComputeWorkload.INFERENCE,
            ComputeWorkload.EMBEDDING,
        ):
            with self.subTest(workload=workload):
                spec = _spec(
                    workload=workload,
                    tags=ComputeTags(project="p1", workload=workload),
                )
                self.assertEqual(
                    runner._environment_reference_for(spec),
                    "azureml:train-env:3",
                )

    def test_falls_back_to_imageryprep_family_setting(self):
        runner = _runner()
        for workload in (
            ComputeWorkload.IMAGERY_PREPARATION,
            ComputeWorkload.ARTIFACT_PACKAGING,
        ):
            with self.subTest(workload=workload):
                spec = _spec(
                    workload=workload,
                    tags=ComputeTags(project="p1", workload=workload),
                )
                self.assertEqual(
                    runner._environment_reference_for(spec),
                    "azureml:imageryprep-env:2",
                )

    def test_raises_when_neither_source_is_configured(self):
        runner = _runner(
            environment_by_workload={w: None for w in ComputeWorkload}
        )
        with self.assertRaises(BackendConfigurationError):
            runner._environment_reference_for(_spec())


class TestPatternStaticDirectory(unittest.TestCase):
    def test_single_level_wildcard(self):
        self.assertEqual(_pattern_static_directory("outputs/*.tif"), "outputs")
        self.assertEqual(_pattern_static_directory("logs/*.log"), "logs")

    def test_recursive_wildcard_directory(self):
        self.assertEqual(
            _pattern_static_directory("inference/**/*"), "inference"
        )

    def test_root_recursive_pattern(self):
        self.assertEqual(_pattern_static_directory("**/*"), "")

    def test_root_shallow_wildcard(self):
        self.assertEqual(_pattern_static_directory("*.log"), "")

    def test_literal_top_level_file(self):
        self.assertEqual(_pattern_static_directory("manifest.json"), "")

    def test_literal_nested_file_with_no_wildcard(self):
        self.assertEqual(
            _pattern_static_directory("logs/manifest.json"), "logs"
        )

    def test_multi_segment_static_directory(self):
        self.assertEqual(
            _pattern_static_directory("checkpoints/best/*.pt"),
            "checkpoints/best",
        )


class TestResolveOutputLayout(unittest.TestCase):
    def test_single_root_pattern(self):
        is_root, static_dirs = _resolve_output_layout([_output("**/*")])
        self.assertTrue(is_root)
        self.assertEqual(static_dirs, [])

    def test_multiple_root_patterns_are_fine(self):
        is_root, static_dirs = _resolve_output_layout(
            [_output("**/*"), _output("**/*", name="other")]
        )
        self.assertTrue(is_root)
        self.assertEqual(static_dirs, [])

    def test_multiple_distinct_static_directories(self):
        is_root, static_dirs = _resolve_output_layout(
            [
                _output("outputs/*.tif", name="a"),
                _output("logs/*.log", name="b"),
            ]
        )
        self.assertFalse(is_root)
        self.assertEqual(static_dirs, ["logs", "outputs"])

    def test_same_static_directory_from_two_outputs_is_deduplicated(self):
        is_root, static_dirs = _resolve_output_layout(
            [
                _output("outputs/*.tif", name="a"),
                _output("outputs/*.json", name="b"),
            ]
        )
        self.assertFalse(is_root)
        self.assertEqual(static_dirs, ["outputs"])

    def test_mixing_root_and_static_directory_raises(self):
        with self.assertRaises(ValueError):
            _resolve_output_layout(
                [
                    _output("**/*", name="a"),
                    _output("outputs/*.tif", name="b"),
                ]
            )

    def test_overlapping_static_directories_raise(self):
        with self.assertRaises(ValueError):
            _resolve_output_layout(
                [
                    _output("outputs/*.tif", name="a"),
                    _output("outputs/nested/*.tif", name="b"),
                ]
            )

    def test_non_overlapping_similarly_named_directories_are_fine(self):
        # "outputs" and "outputs2" must not be mistaken for an overlap —
        # the check is a real path-segment prefix, not a string prefix.
        is_root, static_dirs = _resolve_output_layout(
            [
                _output("outputs/*.tif", name="a"),
                _output("outputs2/*.tif", name="b"),
            ]
        )
        self.assertFalse(is_root)
        self.assertEqual(static_dirs, ["outputs", "outputs2"])


class TestBuildBootstrapCommand(unittest.TestCase):
    def test_binds_haste_job_workdir_directly_to_the_output_root_for_root_pattern(  # noqa: E501
        self,
    ):
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        self.assertIn(
            'export HASTE_OUTPUT_ROOT="${{outputs.haste_output}}"', command
        )
        self.assertIn('export HASTE_JOB_WORKDIR="$HASTE_OUTPUT_ROOT"', command)
        self.assertIn('cd "$HASTE_JOB_WORKDIR"', command)
        # Bound directly to the output root (via HASTE_OUTPUT_ROOT) — no
        # separate symlinked ``outputs/`` subfolder, so root-level writes
        # (checkpoints, progress logs, manifests) land in the durable
        # output too, for a root (``**/*``) output pattern.
        self.assertEqual(command.count("${{outputs.haste_output}}"), 1)
        self.assertNotIn('" outputs\n', command)

    def test_legacy_aliases_resolve_to_the_same_root(self):
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        self.assertIn(
            'export AZ_BATCH_TASK_WORKING_DIR="$HASTE_JOB_WORKDIR"', command
        )
        self.assertIn("export AZ_BATCH_JOB_ID=job-1", command)
        self.assertIn("export AZ_BATCH_TASK_ID=exec-1", command)
        self.assertEqual(_workload_command_line(command), "python run.py")

    def test_quotes_job_and_task_ids_with_special_characters(self):
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job with space",
            task_id="exec$(danger)",
            inner_command="python run.py",
        )
        self.assertIn("export AZ_BATCH_JOB_ID='job with space'", command)
        self.assertIn("export AZ_BATCH_TASK_ID='exec$(danger)'", command)

    def test_stages_each_input_via_symlink_from_named_input_token(self):
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            ),
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/models/",
                kind=InputKind.FOLDER,
                destinationRelativePath="model dir/v1",
                deliveryMode=InputDeliveryMode.MOUNT,
            ),
        ]
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=inputs,
            input_names=["input_0", "input_1"],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        self.assertIn('ln -sfn "${{inputs.input_0}}" in/f.tif', command)
        self.assertIn(
            "ln -sfn \"${{inputs.input_1}}\" 'model dir/v1'", command
        )
        self.assertIn('mkdir -p "$(dirname in/f.tif)"', command)

    def test_input_staging_happens_beneath_the_durable_root(self):
        # Inputs are staged *after* HASTE_JOB_WORKDIR is bound/cd'd into,
        # so destinationRelativePath is resolved relative to the durable
        # output root, not some other directory.
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            )
        ]
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=inputs,
            input_names=["input_0"],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        lines = command.splitlines()
        workdir_cd_idx = lines.index('cd "$HASTE_JOB_WORKDIR"')
        stage_idx = next(
            i for i, line in enumerate(lines) if "input_0" in line
        )
        self.assertLess(workdir_cd_idx, stage_idx)

    def test_changes_directory_into_configured_working_directory(self):
        command = _build_bootstrap_command(
            working_directory="workspace/sub",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        self.assertIn("mkdir -p workspace/sub", command)
        self.assertIn("cd workspace/sub", command)

    def test_default_working_directory_only_cds_into_the_durable_root(self):
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python run.py",
        )
        # Exactly one `cd` — into $HASTE_JOB_WORKDIR itself — so a
        # root-level write by inner_command (e.g. a checkpoint or log
        # file with no subdirectory) lands directly under the durable
        # output root, not some other working directory.
        self.assertEqual(command.count("\ncd "), 1)

    def test_root_level_and_nested_writes_both_resolve_under_durable_root(
        self,
    ):
        # Structural proof (not a live filesystem check): with the
        # default working directory, nothing changes directory between
        # binding $HASTE_JOB_WORKDIR to the output token and invoking
        # inner_command, so both a bare relative path (root-level
        # checkpoint/log) and a nested one (e.g. "logs/progress.log")
        # inner_command might write are relative to the same durable
        # root — there is no separate "outputs/" convention to divert
        # only some of them.
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command="python train.py",
        )
        lines = command.splitlines()
        workdir_cd_idx = lines.index('cd "$HASTE_JOB_WORKDIR"')
        inner_idx = lines.index("set +e") + 1
        between = lines[workdir_cd_idx + 1 : inner_idx]
        self.assertFalse(
            any(line.startswith("cd ") for line in between),
            msg=f"unexpected intermediate cd in: {between}",
        )
        self.assertEqual(_workload_command_line(command), "python train.py")

    def test_inner_command_is_never_mutated_or_re_quoted(self):
        inner = "python run.py --arg 'value with spaces'"
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command=inner,
        )
        self.assertEqual(_workload_command_line(command), inner)

    # -- quoted, workload-shaped commands (processor parity) ------------
    #
    # Every migrated processor's build_*_job_spec() emits `command` as its
    # whole shell chain wrapped in one outer quote — the shape the
    # Batch/local adapters expect. Proves the bootstrap script runs that
    # chain directly rather than mistaking the quoted blob for a single
    # (non-existent) command name.

    def _assert_quoted_wrapper_normalized_to_real_chain(self, inner):
        # Left as supplied, the processor command parses as exactly one
        # shell word — this is the bug: a shell would try to exec a
        # program literally named that whole multi-word string.
        self.assertEqual(len(shlex.split(inner)), 1)

        command = _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command=inner,
        )
        workload_line = _workload_command_line(command)

        self.assertFalse(workload_line.startswith(("'", '"')))
        self.assertEqual(workload_line, inner[1:-1])
        # Now parses as the real multi-word chain a shell would actually
        # execute (cd, &&, python, its arguments, ...), not one token.
        self.assertGreater(len(shlex.split(workload_line)), 1)
        return workload_line

    def test_training_style_double_quoted_command_executes_as_a_chain(self):
        inner = (
            '"cd /app && python run_workflow.py --mode train '
            '--config config.yaml"'
        )
        self._assert_quoted_wrapper_normalized_to_real_chain(inner)

    def test_inference_style_single_quoted_command_executes_as_a_chain(self):
        inner = (
            "'cd /app && python run_workflow.py --mode inference "
            "--config config.yaml --checkpoint model.pt'"
        )
        self._assert_quoted_wrapper_normalized_to_real_chain(inner)

    def test_embedding_style_double_quoted_command_executes_as_a_chain(self):
        inner = (
            '"cd /app && python run_workflow.py --mode embed '
            '--config config.yaml"'
        )
        self._assert_quoted_wrapper_normalized_to_real_chain(inner)

    def test_imagery_prep_style_single_quoted_command_executes_as_a_chain(
        self,
    ):
        inner = "'cd /app && python prepare_imagery.py --config config.yaml'"
        self._assert_quoted_wrapper_normalized_to_real_chain(inner)

    def test_artifact_packaging_style_command_executes_as_a_chain(self):
        inner = (
            '"cd /app && python zip_artifacts.py '
            "--training training_output --inference inference_output"
            '"'
        )
        self._assert_quoted_wrapper_normalized_to_real_chain(inner)

    def test_artifact_packaging_folder_inputs_preserve_destination_paths(
        self,
    ):
        # Artifact packaging takes training/inference OUTPUT FOLDERS as
        # inputs (design.md#workload-migration-matrix). Folder-kind
        # inputs must still land at their neutral destinationRelativePath
        # (as a real directory, via symlink) regardless of backend, and
        # this must hold together with the quoted-command normalization
        # above (the workload command's provider-shape handling).
        inputs = [
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/train-out/",
                kind=InputKind.FOLDER,
                destinationRelativePath="training_output",
            ),
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/infer-out/",
                kind=InputKind.FOLDER,
                destinationRelativePath="inference_output",
            ),
        ]
        inner = (
            '"cd /app && python zip_artifacts.py '
            "--training training_output --inference inference_output"
            '"'
        )
        command = _build_bootstrap_command(
            working_directory=".",
            inputs=inputs,
            input_names=["input_0", "input_1"],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command=inner,
        )

        self.assertIn('ln -sfn "${{inputs.input_0}}" training_output', command)
        self.assertIn(
            'ln -sfn "${{inputs.input_1}}" inference_output', command
        )
        workload_line = _workload_command_line(command)
        self.assertEqual(
            workload_line,
            "cd /app && python zip_artifacts.py --training "
            "training_output --inference inference_output",
        )
        self.assertGreater(len(shlex.split(workload_line)), 1)


class TestNormalizeQuotedCommand(unittest.TestCase):
    def test_strips_double_quoted_wrapper(self):
        self.assertEqual(
            _normalize_quoted_command('"cd /app && python x.py"'),
            "cd /app && python x.py",
        )

    def test_strips_single_quoted_wrapper(self):
        self.assertEqual(
            _normalize_quoted_command("'cd /app && python x.py'"),
            "cd /app && python x.py",
        )

    def test_preserves_inner_quotes_after_stripping_outer_pair(self):
        inner = 'python x.py --arg "value with spaces"'
        wrapped = f"'{inner}'"
        self.assertEqual(_normalize_quoted_command(wrapped), inner)

    def test_leaves_mismatched_quotes_unchanged(self):
        value = "\"cd /app && python x.py'"
        self.assertEqual(_normalize_quoted_command(value), value)

    def test_leaves_lone_leading_quote_unchanged(self):
        value = "'cd /app && python x.py"
        self.assertEqual(_normalize_quoted_command(value), value)

    def test_leaves_lone_trailing_quote_unchanged(self):
        value = "cd /app && python x.py'"
        self.assertEqual(_normalize_quoted_command(value), value)

    def test_leaves_unquoted_command_unchanged(self):
        value = "cd /app && python x.py"
        self.assertEqual(_normalize_quoted_command(value), value)

    def test_leaves_empty_string_unchanged(self):
        self.assertEqual(_normalize_quoted_command(""), "")

    def test_leaves_single_character_quote_unchanged(self):
        self.assertEqual(_normalize_quoted_command("'"), "'")


class TestBootstrapCommandFinalizationShape(unittest.TestCase):
    """Structural assertions on the ENTRYPOINT-bypass hardening footer:
    ``umask 0022``, running the workload with errexit suspended, exit-code
    capture, best-effort recursive chmod, and re-exit with the captured
    code — without invoking a real shell (see
    ``TestBootstrapCommandLiveExecution`` below for that).
    """

    def _command(self, inner_command="python run.py"):
        return _build_bootstrap_command(
            working_directory=".",
            inputs=[],
            input_names=[],
            outputs=_root_outputs(),
            job_id="job-1",
            task_id="exec-1",
            inner_command=inner_command,
        )

    def test_umask_is_set_immediately_after_errexit_and_before_any_staging(
        self,
    ):
        lines = self._command().splitlines()
        self.assertEqual(lines[0], "set -euo pipefail")
        self.assertEqual(lines[1], "umask 0022")
        workdir_export_idx = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("export HASTE_JOB_WORKDIR=")
        )
        self.assertLess(lines.index("umask 0022"), workdir_export_idx)

    def test_workload_runs_immediately_after_errexit_is_suspended(self):
        command = self._command()
        self.assertEqual(_workload_command_line(command), "python run.py")

    def test_exit_code_is_captured_immediately_after_the_workload_runs(self):
        lines = self._command().splitlines()
        set_plus_e_idx = lines.index("set +e")
        workload_line_idx = set_plus_e_idx + 1
        self.assertEqual(
            lines[workload_line_idx + 1], "HASTE_INNER_EXIT_CODE=$?"
        )

    def test_stdout_and_stderr_are_redirected_to_the_durable_output_root(
        self,
    ):
        command = self._command()
        lines = command.splitlines()
        workload_line = lines[lines.index("set +e") + 1]
        self.assertIn('> "$HASTE_OUTPUT_ROOT/stdout.txt"', workload_line)
        self.assertIn('2> "$HASTE_OUTPUT_ROOT/stderr.txt"', workload_line)
        # Deliberately plain redirection, never a `tee`-via-process-
        # substitution "capture and also stream live" design — the
        # latter is a documented, platform-dependent hang risk for
        # anything that waits on this script's own stdout/stderr
        # reaching EOF.
        self.assertNotIn(">(", workload_line)

    def test_errexit_is_restored_immediately_after_capture(self):
        lines = self._command().splitlines()
        capture_idx = lines.index("HASTE_INNER_EXIT_CODE=$?")
        self.assertEqual(lines[capture_idx + 1], "set -e")

    def test_chmod_is_recursive_best_effort_and_targets_the_durable_root(
        self,
    ):
        command = self._command()
        self.assertIn('chmod -R o+rX "$HASTE_OUTPUT_ROOT" || true', command)

    def test_chmod_runs_after_capture_and_before_the_final_exit(self):
        lines = self._command().splitlines()
        capture_idx = lines.index("HASTE_INNER_EXIT_CODE=$?")
        chmod_idx = next(
            i for i, line in enumerate(lines) if line.startswith("chmod ")
        )
        exit_idx = lines.index('exit "$HASTE_INNER_EXIT_CODE"')
        self.assertLess(capture_idx, chmod_idx)
        self.assertLess(chmod_idx, exit_idx)

    def test_final_line_re_exits_with_the_captured_workload_exit_code(self):
        command = self._command()
        self.assertTrue(
            command.strip().endswith('exit "$HASTE_INNER_EXIT_CODE"')
        )

    def test_quoted_workload_command_is_still_normalized_first(self):
        command = self._command(inner_command="'cd /app && python x.py'")
        self.assertEqual(
            _workload_command_line(command), "cd /app && python x.py"
        )


def _find_posix_bash():
    """Locate a real POSIX ``bash`` usable for live-execution tests.

    On Windows, ``shutil.which("bash")`` frequently resolves to the WSL
    launcher stub (``%SystemRoot%\\System32\\bash.exe``), which fails
    immediately if no WSL distro provides ``/bin/bash`` — a false
    positive that would make these tests fail rather than skip. Prefer
    Git for Windows' real bash if present, then fall back to whatever
    ``bash`` resolves to, validating each candidate by actually running
    it before trusting it.
    """
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    which_result = shutil.which("bash")
    if which_result:
        candidates.append(which_result)
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "exit 0"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


_BASH_PATH = _find_posix_bash()


def _to_posix_path(windows_path: str) -> str:
    """Convert a native (possibly Windows/backslash-style) path to the
    POSIX-style path ``_BASH_PATH`` itself resolves paths with.

    Needed for live-execution tests on Windows: ``bash``/MSYS auto-
    translates a raw Windows path for some builtins (``cd``) but not for
    plain string arguments like an ``ln -s`` target, so a real Windows
    path substituted verbatim for ``${{outputs.haste_output}}`` silently
    resolves to the wrong place for anything other than ``cd``. On a real
    POSIX host (Linux, as AML/Batch containers actually run), ``cygpath``
    does not exist and this is a no-op passthrough.
    """
    probe = subprocess.run(
        [
            _BASH_PATH,
            "-c",
            f"command -v cygpath >/dev/null 2>&1 && "
            f"cygpath -u {shlex.quote(windows_path)} || "
            f"printf '%s' {shlex.quote(windows_path)}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return probe.stdout.strip()


def _symlinks_supported() -> bool:
    """Probe whether ``_BASH_PATH`` can create *real* symlinks here.

    On Windows, ``ln -s`` without Developer Mode or Administrator
    privileges silently creates an ordinary empty directory instead of a
    symlink (no error) — the durable-output-flattening live-execution
    tests below need a real symlink to prove anything, so they must be
    skipped rather than given a false failure on such a host. On a real
    POSIX host (Linux, as AML actually runs), this always succeeds.
    """
    if not _BASH_PATH:
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "target")
            link = os.path.join(tmp, "link")
            os.makedirs(target)
            posix_target = _to_posix_path(target)
            posix_link = _to_posix_path(link)
            probe = subprocess.run(
                [
                    _BASH_PATH,
                    "-c",
                    f"ln -sfn {shlex.quote(posix_target)} "
                    f"{shlex.quote(posix_link)}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return probe.returncode == 0 and os.path.islink(link)
    except (OSError, subprocess.SubprocessError):
        return False


_SYMLINKS_SUPPORTED = _symlinks_supported()


@unittest.skipUnless(_BASH_PATH, "no POSIX shell (bash) on this host")
class TestBootstrapCommandLiveExecution(unittest.TestCase):
    """Executes the generated bootstrap script against a real ``bash``,
    simulating AML's own ``${{outputs.haste_output}}`` template
    substitution with a real temporary directory, to prove — not just
    structurally assert — that finalization runs on both success and
    failure and that the workload's real exit code survives it.
    """

    def _run(self, inner_command, *, trace=False, after=None):
        with tempfile.TemporaryDirectory() as workdir:
            script = _build_bootstrap_command(
                working_directory=".",
                inputs=[],
                input_names=[],
                outputs=_root_outputs(),
                job_id="job-1",
                task_id="exec-1",
                inner_command=inner_command,
            )
            # AML resolves this token to the job's real local output path
            # before bash ever sees the script; simulate that here. Uses
            # the POSIX-translated form so bash's own internal file-open
            # syscalls (stdout/stderr redirection targets built from this
            # value) resolve correctly, same as the flattening classes'
            # ``ln -s`` targets need.
            script = script.replace(
                "${{outputs.haste_output}}", _to_posix_path(workdir)
            )
            args = [_BASH_PATH]
            if trace:
                args.append("-x")
            args += ["-c", script]
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=30
            )
            if after is not None:
                after(result, workdir)
            return result

    def test_success_exits_zero(self):
        result = self._run("'true'")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_failure_preserves_the_workloads_exact_exit_code(self):
        # A real failing workload is a separate *process* returning a
        # non-zero status to bash — never the ``exit`` builtin, which
        # would terminate this bootstrap script's own shell immediately
        # (before capture/finalization ever run). ``(exit 42)`` runs in a
        # subshell, so it behaves like a real failing process: bash sees
        # a non-zero ``$?`` and continues, rather than the parent shell
        # itself exiting.
        result = self._run("'(exit 42)'")
        self.assertEqual(result.returncode, 42, msg=result.stderr)

    def test_a_failing_real_shell_chain_preserves_its_exit_code(self):
        # Mirrors an actual workload command shape (cd, &&, a failing
        # step) — proves errexit suspension covers the whole chain, not
        # just a single bare command, and that the final captured code
        # is the chain's own failure code, not a generic 1.
        result = self._run("'true && (exit 17)'")
        self.assertEqual(result.returncode, 17, msg=result.stderr)

    def test_stdout_and_stderr_are_captured_to_durable_files_on_success(
        self,
    ):
        captured = {}

        def _record(result, workdir):
            with open(os.path.join(workdir, "stdout.txt")) as f:
                captured["stdout"] = f.read()
            with open(os.path.join(workdir, "stderr.txt")) as f:
                captured["stderr"] = f.read()

        result = self._run("'echo out-line; echo err-line >&2'", after=_record)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("out-line", captured["stdout"])
        self.assertIn("err-line", captured["stderr"])

    def test_stdout_and_stderr_are_captured_to_durable_files_on_failure(
        self,
    ):
        # The core diagnostic-availability regression this targets: a
        # failed job's console output must still be durably readable
        # afterward (via the same bounded read_output path other outputs
        # use), not just visible transiently while the job runs.
        captured = {}

        def _record(result, workdir):
            with open(os.path.join(workdir, "stdout.txt")) as f:
                captured["stdout"] = f.read()
            with open(os.path.join(workdir, "stderr.txt")) as f:
                captured["stderr"] = f.read()

        result = self._run(
            "'echo out-line; echo err-line >&2; (exit 5)'", after=_record
        )
        self.assertEqual(result.returncode, 5, msg=result.stderr)
        self.assertIn("out-line", captured["stdout"])
        self.assertIn("err-line", captured["stderr"])

    def test_finalization_runs_on_success_not_just_on_failure(self):
        result = self._run("'true'", trace=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("chmod -R o+rX", result.stderr)

    def test_finalization_runs_on_failure_and_is_not_skipped_by_errexit(
        self,
    ):
        # The core regression this hardening targets: a failing workload
        # under `set -e` must not abort the script before finalization.
        # returncode 7 can only be reported by the final
        # `exit "$HASTE_INNER_EXIT_CODE"` line, itself unconditionally
        # preceded by the chmod line — so a returncode of exactly 7 (the
        # workload's own code, not some earlier bash syntax/abort error)
        # already proves finalization was reached; the `-x` trace
        # additionally confirms the chmod line itself actually executed
        # (not, e.g., skipped by a typo making it dead code).
        result = self._run("'true && (exit 7)'", trace=True)
        self.assertEqual(result.returncode, 7, msg=result.stderr)
        self.assertIn("chmod", result.stderr)


@unittest.skipUnless(_BASH_PATH, "no POSIX shell (bash) on this host")
class TestBootstrapCommandLiveExecutionRootLayout(unittest.TestCase):
    """Executes the generated bootstrap script against a real ``bash`` for
    training's root (``**/*``) output pattern (design.md#workload-
    migration-matrix), proving full directory structure is preserved —
    not flattened — for the files a workload's inner command writes.

    Unlike the static-directory layout (see
    ``TestBootstrapCommandLiveExecutionFlattening`` below), the root
    layout binds ``HASTE_JOB_WORKDIR`` directly to the durable output
    root with no symlink involved, so this class only needs a working
    ``bash``, not real symlink support.
    """

    def _run(self, outputs, write_commands):
        with tempfile.TemporaryDirectory() as output_root:
            write_script = " && ".join(write_commands)
            script = _build_bootstrap_command(
                working_directory=".",
                inputs=[],
                input_names=[],
                outputs=outputs,
                job_id="job-1",
                task_id="exec-1",
                inner_command=f"'{write_script}'",
            )
            script = script.replace(
                "${{outputs.haste_output}}", _to_posix_path(output_root)
            )
            result = subprocess.run(
                [_BASH_PATH, "-c", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # stdout.txt/stderr.txt are always written under the durable
            # root (see TestBootstrapCommandLiveExecution's own dedicated
            # coverage) — excluded here since this class is purely about
            # root-layout structure preservation.
            found = {
                os.path.relpath(
                    os.path.join(dirpath, fname), output_root
                ).replace("\\", "/")
                for dirpath, _dirs, files in os.walk(output_root)
                for fname in files
            }
            return found - {"stdout.txt", "stderr.txt"}

    def test_training_root_pattern_preserves_full_structure(self):
        # Training's checkpoints/TensorBoard events/progress logs must
        # keep their real nested paths, not be flattened, so later reads
        # (e.g. a specific checkpoint, or TensorBoard scanning a "logs/"
        # subdirectory) find them where they were actually written.
        outputs = [_output("**/*", name="everything")]
        found = self._run(
            outputs,
            [
                "mkdir -p checkpoints logs",
                "echo ckpt > checkpoints/model.pt",
                "echo tfevent > logs/events.out.tfevents.123",
                "echo progress > progress.log",
            ],
        )
        self.assertEqual(
            found,
            {
                "checkpoints/model.pt",
                "logs/events.out.tfevents.123",
                "progress.log",
            },
        )


@unittest.skipUnless(_BASH_PATH, "no POSIX shell (bash) on this host")
@unittest.skipUnless(
    _SYMLINKS_SUPPORTED,
    "this host's bash cannot create real symlinks (no Developer Mode/"
    "Administrator privilege) — flattening cannot be proven via live "
    "execution here; see design.md#aml-submission-mapping",
)
class TestBootstrapCommandLiveExecutionFlattening(unittest.TestCase):
    """Executes the generated bootstrap script against a real ``bash`` for
    each workload's realistic static-directory output-pattern shape
    (design.md#workload-migration-matrix), proving the files a workload's
    inner command actually writes land *flattened* onto the durable
    output root — reproducing Azure Batch's own upload flattening of a
    wildcarded ``sourceRelativePattern`` — rather than nested under the
    pattern's own local directory.
    """

    def _run(self, outputs, write_commands):
        with tempfile.TemporaryDirectory() as output_root:
            write_script = " && ".join(write_commands)
            script = _build_bootstrap_command(
                working_directory=".",
                inputs=[],
                input_names=[],
                outputs=outputs,
                job_id="job-1",
                task_id="exec-1",
                inner_command=f"'{write_script}'",
            )
            script = script.replace(
                "${{outputs.haste_output}}", _to_posix_path(output_root)
            )
            result = subprocess.run(
                [_BASH_PATH, "-c", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # stdout.txt/stderr.txt are always written under the durable
            # root (see TestBootstrapCommandLiveExecution's own dedicated
            # coverage) — excluded here since these tests are purely
            # about pattern-based output-layout flattening.
            found = {
                os.path.relpath(
                    os.path.join(dirpath, fname), output_root
                ).replace("\\", "/")
                for dirpath, _dirs, files in os.walk(output_root)
                for fname in files
            }
            return found - {"stdout.txt", "stderr.txt"}

    def test_imagery_preparation_outputs_and_logs_flatten_to_the_root(self):
        # Imagery prep's COGs/previews/footprints/manifests land under
        # "outputs/", its friendly log under "logs/" — Batch uploads both
        # flattened onto the same destination prefix.
        outputs = [
            _output("outputs/*.tif", name="cog"),
            _output("logs/*.log", name="friendly-log"),
        ]
        found = self._run(
            outputs,
            [
                "mkdir -p outputs logs",
                "echo cog > outputs/result.tif",
                "echo log > logs/friendly.log",
            ],
        )
        self.assertEqual(found, {"result.tif", "friendly.log"})

    def test_inference_output_flattens_to_the_root(self):
        outputs = [_output("inference/*.tif", name="inference-cog")]
        found = self._run(
            outputs,
            ["mkdir -p inference", "echo cog > inference/result.tif"],
        )
        self.assertEqual(found, {"result.tif"})

    def test_embedding_output_flattens_to_the_root(self):
        outputs = [_output("embedding/*.geojson", name="embedding-out")]
        found = self._run(
            outputs,
            [
                "mkdir -p embedding",
                "echo geo > embedding/output.geojson",
            ],
        )
        self.assertEqual(found, {"output.geojson"})

    def test_artifact_packaging_outputs_flatten_to_the_root(self):
        outputs = [_output("outputs/*.zip", name="artifacts")]
        found = self._run(
            outputs,
            [
                "mkdir -p outputs",
                "echo a > outputs/training.zip",
                "echo b > outputs/inference.zip",
            ],
        )
        self.assertEqual(found, {"training.zip", "inference.zip"})

    def test_multiple_static_directories_share_one_flattened_root(self):
        # Explicit proof of "multiple prefixes may point to the same
        # root" — files from two different local static directories end
        # up as siblings in the one durable output, not just each
        # individually flattened.
        outputs = [
            _output("outputs/*.tif", name="a"),
            _output("logs/*.log", name="b"),
        ]
        found = self._run(
            outputs,
            [
                "mkdir -p outputs logs",
                "echo a > outputs/one.tif",
                "echo b > logs/two.log",
            ],
        )
        self.assertEqual(found, {"one.tif", "two.log"})


class TestSanitizedTags(unittest.TestCase):
    def test_includes_requested_spot_flag(self):
        spec = _spec(resources=ComputeResources(allowSpot=True))
        tags = _sanitized_tags(spec)
        self.assertEqual(tags["requestedSpot"], "true")
        self.assertEqual(tags["project"], "p1")

    def test_requested_spot_false_by_default(self):
        tags = _sanitized_tags(_spec())
        self.assertEqual(tags["requestedSpot"], "false")

    def test_includes_execution_id(self):
        tags = _sanitized_tags(_spec(executionId="exec-42"))
        self.assertEqual(tags["executionId"], "exec-42")


class TestSubmit(unittest.TestCase):
    def test_creates_new_job_when_none_exists(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        created = _job(name="haste-exec-1", status="Queued")
        client.jobs.create_or_update.return_value = created
        runner = _runner(client=client)

        handle = runner.submit(_spec())

        client.jobs.create_or_update.assert_called_once()
        self.assertEqual(handle.executionId, "exec-1")
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_ML)
        self.assertEqual(handle.providerJobId, "haste-exec-1")
        self.assertIsNone(handle.providerTaskId)
        self.assertEqual(handle.targetId, "gpu-cluster")
        self.assertEqual(
            handle.outputUri,
            "https://a.blob.core.windows.net/data/proj/task-1/",
        )
        self.assertEqual(handle.providerDetail.discriminator, "azure_ml")
        self.assertEqual(handle.providerDetail.azureMl.jobName, "haste-exec-1")
        self.assertEqual(handle.providerDetail.azureMl.workspace, "ws-1")

    def test_command_job_kwargs_map_spec_fields(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = lambda job: _job(
            name=job.name, status="Queued"
        )
        runner = _runner(client=client)

        spec = _spec(
            resources=ComputeResources(
                nodeCount=2, sharedMemoryMb=2048, allowSpot=True
            ),
            environment={"MY_FLAG": "1"},
            timeoutSeconds=7200,
        )
        runner.submit(spec)

        job = client.jobs.create_or_update.call_args.args[0]
        self.assertEqual(job.compute, "gpu-cluster")
        self.assertEqual(job.environment, "azureml:train-env:3")
        self.assertEqual(job.environment_variables, {"MY_FLAG": "1"})
        self.assertEqual(job.resources.instance_count, 2)
        self.assertEqual(job.resources.shm_size, "2048m")
        self.assertEqual(job.limits.timeout, 7200)
        self.assertEqual(job.tags["requestedSpot"], "true")
        self.assertIn("input_0", job.inputs)
        self.assertEqual(job.inputs["input_0"].path, spec.inputs[0].sourceUri)
        self.assertIn("haste_output", job.outputs)
        self.assertIn(
            "azureml://datastores/haste-datastore/paths/proj/task-1",
            job.outputs["haste_output"].path,
        )

    def test_artifact_packaging_spec_maps_folder_inputs_and_command(self):
        # End-to-end (submit -> command job) proof that artifact
        # packaging's folder-input contract and the quoted-command
        # normalization compose correctly through the real submission
        # path, not just the bootstrap-command helper in isolation.
        from azure.ai.ml.constants import AssetTypes

        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = lambda job: _job(
            name=job.name, status="Queued"
        )
        runner = _runner(client=client)

        quoted_command = (
            '"cd /app && python zip_artifacts.py '
            "--training training_output --inference inference_output"
            '"'
        )
        spec = _spec(
            workload=ComputeWorkload.ARTIFACT_PACKAGING,
            tags=ComputeTags(
                project="p1", workload=ComputeWorkload.ARTIFACT_PACKAGING
            ),
            command=quoted_command,
            inputs=[
                ComputeInput(
                    sourceUri=("https://a.blob.core.windows.net/c/train-out/"),
                    kind=InputKind.FOLDER,
                    destinationRelativePath="training_output",
                ),
                ComputeInput(
                    sourceUri=("https://a.blob.core.windows.net/c/infer-out/"),
                    kind=InputKind.FOLDER,
                    destinationRelativePath="inference_output",
                ),
            ],
        )
        runner.submit(spec)

        job = client.jobs.create_or_update.call_args.args[0]
        self.assertEqual(job.compute, "cpu-cluster")
        self.assertEqual(job.environment, "azureml:imageryprep-env:2")
        self.assertEqual(job.inputs["input_0"].type, AssetTypes.URI_FOLDER)
        self.assertEqual(job.inputs["input_1"].type, AssetTypes.URI_FOLDER)

        workload_line = _workload_command_line(job.command)
        self.assertEqual(
            workload_line,
            "cd /app && python zip_artifacts.py --training "
            "training_output --inference inference_output",
        )
        self.assertGreater(len(shlex.split(workload_line)), 1)
        self.assertIn(
            'ln -sfn "${{inputs.input_0}}" training_output', job.command
        )
        self.assertIn(
            'ln -sfn "${{inputs.input_1}}" inference_output', job.command
        )

    def test_output_mode_is_upload_by_default(self):
        from azure.ai.ml.constants import InputOutputModes

        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = lambda job: _job(
            name=job.name, status="Queued"
        )
        runner = _runner(client=client)
        runner.submit(_spec())
        job = client.jobs.create_or_update.call_args.args[0]
        self.assertEqual(
            job.outputs["haste_output"].mode, InputOutputModes.UPLOAD
        )

    def test_output_mode_is_rw_mount_when_any_output_is_live_mount(self):
        from azure.ai.ml.constants import InputOutputModes

        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = lambda job: _job(
            name=job.name, status="Queued"
        )
        runner = _runner(client=client)
        spec = _spec(
            outputs=[
                ComputeOutput(
                    name="progress",
                    sourceRelativePattern="progress.log",
                    destinationUri=(
                        "https://a.blob.core.windows.net/data/proj/task-1/"
                    ),
                    persistenceMode=OutputPersistenceMode.LIVE_MOUNT,
                )
            ]
        )
        runner.submit(spec)
        job = client.jobs.create_or_update.call_args.args[0]
        self.assertEqual(
            job.outputs["haste_output"].mode, InputOutputModes.RW_MOUNT
        )

    def test_idempotent_get_before_create_reconciles_existing_job(self):
        client = MagicMock()
        existing = _job(name="haste-exec-1", status="Running")
        client.jobs.get.return_value = existing
        runner = _runner(client=client)

        handle = runner.submit(_spec())

        client.jobs.create_or_update.assert_not_called()
        self.assertEqual(handle.providerJobId, "haste-exec-1")

    def test_create_conflict_reconciles_via_get(self):
        client = MagicMock()
        existing = _job(name="haste-exec-1", status="Running")
        client.jobs.get.side_effect = [
            ResourceNotFoundError("not found"),
            existing,
        ]
        client.jobs.create_or_update.side_effect = ResourceExistsError(
            "already exists"
        )
        runner = _runner(client=client)

        handle = runner.submit(_spec())
        self.assertEqual(handle.providerJobId, "haste-exec-1")

    def test_create_http_conflict_reconciles_via_get(self):
        client = MagicMock()
        existing = _job(name="haste-exec-1", status="Running")
        client.jobs.get.side_effect = [
            ResourceNotFoundError("not found"),
            existing,
        ]
        client.jobs.create_or_update.side_effect = _http_error(409)
        runner = _runner(client=client)

        handle = runner.submit(_spec())
        self.assertEqual(handle.providerJobId, "haste-exec-1")

    def test_reconciliation_rejects_execution_id_tag_mismatch(self):
        client = MagicMock()
        existing = _job(
            name="haste-exec-1", status="Running", execution_id="other-exec"
        )
        client.jobs.get.return_value = existing
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())
        client.jobs.create_or_update.assert_not_called()

    def test_reconciliation_rejects_execution_id_tag_missing(self):
        client = MagicMock()
        existing = _job(
            name="haste-exec-1", status="Running", execution_id=None
        )
        client.jobs.get.return_value = existing
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_create_conflict_reconciliation_rejects_execution_id_mismatch(
        self,
    ):
        client = MagicMock()
        mismatched = _job(
            name="haste-exec-1", status="Running", execution_id="other-exec"
        )
        client.jobs.get.side_effect = [
            ResourceNotFoundError("not found"),
            mismatched,
        ]
        client.jobs.create_or_update.side_effect = ResourceExistsError(
            "already exists"
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_create_conflict_with_no_reconciliation_target_is_indeterminate(
        self,
    ):
        client = MagicMock()
        client.jobs.get.side_effect = [
            ResourceNotFoundError("not found"),
            ResourceNotFoundError("still not found"),
        ]
        client.jobs.create_or_update.side_effect = ResourceExistsError(
            "already exists"
        )
        runner = _runner(client=client)
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

    def test_create_deterministic_4xx_raises_configuration_error(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = _http_error(400)
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_create_5xx_raises_submission_indeterminate(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = _http_error(503)
        runner = _runner(client=client)
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

    def test_create_429_raises_backend_unavailable(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = _http_error(429)
        runner = _runner(client=client)
        with self.assertRaises(BackendUnavailableError):
            runner.submit(_spec())

    def test_create_network_error_raises_submission_indeterminate(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = ServiceRequestError(
            "timeout"
        )
        runner = _runner(client=client)
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

    def test_get_before_create_network_error_raises_submission_indeterminate(
        self,
    ):
        client = MagicMock()
        client.jobs.get.side_effect = ServiceResponseError("timeout")
        runner = _runner(client=client)
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

    def test_get_before_create_other_http_error_raises_backend_unavailable(
        self,
    ):
        client = MagicMock()
        client.jobs.get.side_effect = _http_error(500)
        runner = _runner(client=client)
        with self.assertRaises(BackendUnavailableError):
            runner.submit(_spec())

    def test_create_validation_exception_raises_configuration_error(self):
        from azure.ai.ml.exceptions import ValidationException

        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = ValidationException(
            message="invalid job specification",
            no_personal_data_message="invalid job specification",
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_create_job_exception_raises_configuration_error(self):
        from azure.ai.ml.exceptions import JobException

        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = JobException(
            message="unsupported job type",
            no_personal_data_message="unsupported job type",
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_get_before_create_validation_exception_raises_configuration_error(  # noqa: E501
        self,
    ):
        from azure.ai.ml.exceptions import ValidationException

        client = MagicMock()
        client.jobs.get.side_effect = ValidationException(
            message="invalid job name",
            no_personal_data_message="invalid job name",
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_target_override_selects_compute_and_target_id(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        client.jobs.create_or_update.side_effect = lambda job: _job(
            name=job.name, status="Queued"
        )
        runner = _runner(client=client)
        spec = _spec(
            resources=ComputeResources(targetOverride="custom-cluster")
        )
        handle = runner.submit(spec)
        job = client.jobs.create_or_update.call_args.args[0]
        self.assertEqual(job.compute, "custom-cluster")
        self.assertEqual(handle.targetId, "custom-cluster")


class TestGetStatus(unittest.TestCase):
    def test_maps_known_statuses(self):
        cases = {
            "NotStarted": ComputeJobState.SUBMITTING,
            "Starting": ComputeJobState.SUBMITTING,
            "Provisioning": ComputeJobState.PREPARING,
            "Preparing": ComputeJobState.PREPARING,
            "Queued": ComputeJobState.QUEUED,
            "Running": ComputeJobState.RUNNING,
            "Finalizing": ComputeJobState.RUNNING,
            "CancelRequested": ComputeJobState.RUNNING,
            "Completed": ComputeJobState.SUCCEEDED,
            "Failed": ComputeJobState.FAILED,
            "Canceled": ComputeJobState.CANCELLED,
            "NotResponding": ComputeJobState.FAILED,
            "Paused": ComputeJobState.QUEUED,
        }
        for raw_status, expected in cases.items():
            with self.subTest(raw_status=raw_status):
                client = MagicMock()
                client.jobs.get.return_value = _job(status=raw_status)
                runner = _runner(client=client)
                self.assertEqual(runner.get_status(_handle()), expected)

    def test_unmapped_status_raises_typed_error(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="SomeNewAmlStatus")
        runner = _runner(client=client)
        with self.assertRaises(UnmappedAmlJobStatusError):
            runner.get_status(_handle())

    def test_not_found_raises_job_not_found_error(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        runner = _runner(client=client)
        with self.assertRaises(JobNotFoundError):
            runner.get_status(_handle())

    def test_other_error_raises_backend_unavailable(self):
        client = MagicMock()
        client.jobs.get.side_effect = _http_error(500)
        runner = _runner(client=client)
        with self.assertRaises(BackendUnavailableError):
            runner.get_status(_handle())

    def test_validation_exception_raises_configuration_error(self):
        from azure.ai.ml.exceptions import ValidationException

        client = MagicMock()
        client.jobs.get.side_effect = ValidationException(
            message="invalid job name",
            no_personal_data_message="invalid job name",
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.get_status(_handle())

    def test_job_exception_raises_configuration_error(self):
        from azure.ai.ml.exceptions import JobException

        client = MagicMock()
        client.jobs.get.side_effect = JobException(
            message="unsupported job",
            no_personal_data_message="unsupported job",
        )
        runner = _runner(client=client)
        with self.assertRaises(BackendConfigurationError):
            runner.get_status(_handle())


class TestReadOutput(unittest.TestCase):
    def _patch_container_client(self, download_blob_side_effect=None):
        patcher = patch("hastegeo.core.runners.azure_ml.ContainerClient")
        mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        container_client = MagicMock()
        mock_cls.from_container_url.return_value = container_client
        blob_client = MagicMock()
        container_client.get_blob_client.return_value = blob_client
        if download_blob_side_effect is not None:
            blob_client.download_blob.side_effect = download_blob_side_effect
        # No nested match by default — tests that exercise the nested-
        # match path configure ``list_blobs`` explicitly.
        container_client.list_blobs.return_value = []
        return blob_client, container_client

    def test_reads_from_durable_storage_when_available(self):
        blob_client, _container_client = self._patch_container_client()
        downloader = MagicMock()
        downloader.readall.return_value = b"hello"
        blob_client.download_blob.return_value = downloader
        runner = _runner()

        result = runner.read_output(_handle(), "progress.log")
        self.assertEqual(result, "hello")

    def test_returns_chunks_when_requested(self):
        blob_client, _container_client = self._patch_container_client()
        downloader = MagicMock()
        downloader.chunks.return_value = iter([b"a", b"b"])
        blob_client.download_blob.return_value = downloader
        runner = _runner()

        result = runner.read_output(_handle(), "progress.log", as_chunks=True)
        self.assertEqual(list(result), [b"a", b"b"])

    def test_falls_back_to_sdk_download_when_blob_not_found(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            import os

            with open(os.path.join(download_path, "progress.log"), "w") as f:
                f.write("from-sdk")

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        result = runner.read_output(_handle(), "progress.log")
        self.assertEqual(result, "from-sdk")

    def test_returns_none_when_neither_source_has_the_file(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()
        client.jobs.download.return_value = None
        runner = _runner(client=client)

        self.assertIsNone(runner.read_output(_handle(), "missing.log"))

    def test_falls_back_when_durable_read_has_other_error(self):
        self._patch_container_client(
            download_blob_side_effect=_http_error(500)
        )
        client = MagicMock()
        client.jobs.download.return_value = None
        runner = _runner(client=client)

        self.assertIsNone(runner.read_output(_handle(), "missing.log"))

    def test_sdk_fallback_not_found_raises_job_not_found_error(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()
        client.jobs.download.side_effect = ResourceNotFoundError("no job")
        runner = _runner(client=client)

        with self.assertRaises(JobNotFoundError):
            runner.read_output(_handle(), "progress.log")

    def test_sdk_fallback_other_error_raises_output_not_available(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()
        client.jobs.download.side_effect = _http_error(500)
        runner = _runner(client=client)

        with self.assertRaises(OutputNotAvailableError):
            runner.read_output(_handle(), "progress.log")

    def test_sdk_fallback_treats_job_not_yet_terminal_as_not_available(self):
        from azure.ai.ml.exceptions import JobException

        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()
        client.jobs.download.side_effect = JobException(
            message="This job is in state Running. Download is allowed "
            "only in states ['Completed', 'Failed', 'Canceled']",
            no_personal_data_message="job not terminal",
        )
        runner = _runner(client=client)

        # Not-yet-downloadable is a normal condition, not an error.
        self.assertIsNone(runner.read_output(_handle(), "progress.log"))

    def test_sdk_fallback_bounds_read_size(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            import os

            from hastegeo.core.runners.azure_ml import _MAX_FALLBACK_READ_BYTES

            with open(os.path.join(download_path, "big.log"), "wb") as f:
                f.write(b"x" * (_MAX_FALLBACK_READ_BYTES + 10))

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        with self.assertRaises(OutputNotAvailableError):
            runner.read_output(_handle(), "big.log")

    def test_sdk_fallback_matches_a_tensorboard_style_basename_prefix(self):
        # The SDK-download fallback's glob must support the same
        # basename-prefix matching as the durable-storage path (a
        # TensorBoard ``events.out.tfevents.<ts>.<host>.<pid>.<n>`` file
        # downloaded locally against a caller-supplied
        # ``events.out.tfevents``).
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            fname = "events.out.tfevents.1700000000.myhost.12345.0"
            with open(os.path.join(download_path, fname), "w") as f:
                f.write("tfevents-from-sdk")

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        result = runner.read_output(_handle(), "events.out.tfevents")
        self.assertEqual(result, "tfevents-from-sdk")

    def test_sdk_fallback_matches_basename_prefix_at_nested_depth(self):
        # Same as above, but the downloaded file lands at a realistic,
        # arbitrarily-nested TensorBoard run path — the recursive glob
        # fallback must not be constrained to the download root's own
        # depth.
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            nested_dir = os.path.join(
                download_path, "logs", "model_abc123", "version_0"
            )
            os.makedirs(nested_dir)
            fname = "events.out.tfevents.1700000000.myhost.12345.0"
            with open(os.path.join(nested_dir, fname), "w") as f:
                f.write("nested-tfevents-from-sdk")

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        result = runner.read_output(_handle(), "events.out.tfevents")
        self.assertEqual(result, "nested-tfevents-from-sdk")

    def test_sdk_fallback_prefers_exact_match_over_prefix_match(self):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            # Both an exact match and a longer-prefixed name exist —
            # the exact match must win, not raise ambiguity.
            with open(
                os.path.join(download_path, "events.out.tfevents"), "w"
            ) as f:
                f.write("exact")
            with open(
                os.path.join(
                    download_path,
                    "events.out.tfevents.1700000000.myhost.1.0",
                ),
                "w",
            ) as f:
                f.write("prefixed")

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        result = runner.read_output(_handle(), "events.out.tfevents")
        self.assertEqual(result, "exact")

    def test_sdk_fallback_raises_ambiguous_error_for_multiple_prefix_matches(
        self,
    ):
        self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()

        def _download(name, download_path, output_name):
            for suffix in ("1700000000.myhost.1.0", "1700000100.myhost.2.0"):
                fname = f"events.out.tfevents.{suffix}"
                with open(os.path.join(download_path, fname), "w") as f:
                    f.write("data")

        client.jobs.download.side_effect = _download
        runner = _runner(client=client)

        with self.assertRaises(AmbiguousOutputMatchError):
            runner.read_output(_handle(), "events.out.tfevents")

    # -- nested-match behavior (Batch get-file-by-match parity) --------

    def _blob(self, name):
        blob = MagicMock()
        blob.name = name
        return blob

    def test_finds_a_unique_nested_match_under_the_job_prefix(self):
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        nested_name = "proj/task-1/outputs/logs/manifest.json"
        container_client.list_blobs.return_value = [self._blob(nested_name)]
        nested_blob_client = MagicMock()
        downloader = MagicMock()
        downloader.readall.return_value = b"nested-content"
        nested_blob_client.download_blob.return_value = downloader

        def _get_blob_client(name):
            if name == nested_name:
                return nested_blob_client
            bc = MagicMock()
            bc.download_blob.side_effect = ResourceNotFoundError("missing")
            return bc

        container_client.get_blob_client.side_effect = _get_blob_client
        runner = _runner()

        result = runner.read_output(_handle(), "manifest.json")
        self.assertEqual(result, "nested-content")

    def test_nested_listing_call_uses_the_handles_own_prefix(self):
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        client = MagicMock()
        client.jobs.download.return_value = None
        runner = _runner(client=client)

        runner.read_output(_handle(), "manifest.json")

        # The nested-suffix search finds nothing (list_blobs.return_value
        # is [] by default), so the basename-prefix fallback search runs
        # too — both bounded to the same job prefix.
        for call in container_client.list_blobs.call_args_list:
            self.assertEqual(call.kwargs, {"name_starts_with": "proj/task-1/"})
        self.assertGreaterEqual(container_client.list_blobs.call_count, 1)

    def test_raises_ambiguous_error_when_multiple_nested_matches(self):
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        container_client.list_blobs.return_value = [
            self._blob("proj/task-1/outputs/a/manifest.json"),
            self._blob("proj/task-1/outputs/b/manifest.json"),
        ]
        client = MagicMock()
        runner = _runner(client=client)

        with self.assertRaises(AmbiguousOutputMatchError):
            runner.read_output(_handle(), "manifest.json")
        # An ambiguous durable-storage match is a definitive failure —
        # never silently masked by trying the SDK fallback instead.
        client.jobs.download.assert_not_called()

    def test_nested_match_falls_back_to_sdk_when_listing_fails(self):
        with patch(
            "hastegeo.core.runners.azure_ml.ContainerClient"
        ) as mock_cls:
            container_client = MagicMock()
            mock_cls.from_container_url.return_value = container_client
            blob_client = MagicMock()
            blob_client.download_blob.side_effect = ResourceNotFoundError(
                "missing"
            )
            container_client.get_blob_client.return_value = blob_client
            container_client.list_blobs.side_effect = _http_error(500)

            client = MagicMock()

            def _download(name, download_path, output_name):
                import os

                with open(
                    os.path.join(download_path, "manifest.json"), "w"
                ) as f:
                    f.write("from-sdk")

            client.jobs.download.side_effect = _download
            runner = _runner(client=client)

            result = runner.read_output(_handle(), "manifest.json")
        self.assertEqual(result, "from-sdk")

    # -- basename-prefix match (TensorBoard event-file parity) ----------

    def test_finds_a_unique_tensorboard_style_basename_prefix_match(self):
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        tfevents_name = (
            "proj/task-1/events.out.tfevents.1700000000.myhost.12345.0"
        )
        container_client.list_blobs.return_value = [self._blob(tfevents_name)]
        tfevents_blob_client = MagicMock()
        downloader = MagicMock()
        downloader.readall.return_value = b"tfevents-content"
        tfevents_blob_client.download_blob.return_value = downloader

        def _get_blob_client(name):
            if name == tfevents_name:
                return tfevents_blob_client
            bc = MagicMock()
            bc.download_blob.side_effect = ResourceNotFoundError("missing")
            return bc

        container_client.get_blob_client.side_effect = _get_blob_client
        runner = _runner()

        result = runner.read_output(_handle(), "events.out.tfevents")
        self.assertEqual(result, "tfevents-content")

    def test_tensorboard_basename_prefix_match_searches_nested_directories(
        self,
    ):
        # A same-basename-prefix blob nested arbitrarily deeper than
        # ``relative_path`` — mirroring TensorBoard's own realistic
        # layout (``logs/<model>/<version>/events.out.tfevents...``) —
        # must still match; depth is deliberately not a constraint.
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        wrong_depth_name = (
            "proj/task-1/other/"
            "events.out.tfevents.1700000000.myhost.12345.0"
        )
        container_client.list_blobs.return_value = [
            self._blob(wrong_depth_name)
        ]
        nested_blob_client = MagicMock()
        nested_blob_client.download_blob.return_value.readall.return_value = (
            b"nested-tfevents"
        )
        container_client.get_blob_client.return_value = nested_blob_client
        runner = _runner()

        self.assertEqual(
            runner.read_output(_handle(), "events.out.tfevents"),
            "nested-tfevents",
        )

    def test_tensorboard_style_match_at_realistic_run_nested_depth(self):
        # The realistic TensorBoard layout: the event file lands several
        # directories deeper than the caller's request, under a
        # model/version-specific path PyTorch Lightning-style loggers
        # commonly produce, e.g.
        # "logs/model_<id>/version_0/events.out.tfevents.<ts>...".
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        realistic_name = (
            "proj/task-1/logs/model_abc123/version_0/"
            "events.out.tfevents.1700000000.myhost.12345.0"
        )
        container_client.list_blobs.return_value = [self._blob(realistic_name)]
        nested_blob_client = MagicMock()
        nested_blob_client.download_blob.return_value.readall.return_value = (
            b"realistic-tfevents"
        )
        container_client.get_blob_client.return_value = nested_blob_client
        runner = _runner()

        self.assertEqual(
            runner.read_output(_handle(), "events.out.tfevents"),
            "realistic-tfevents",
        )

    def test_raises_ambiguous_error_for_multiple_tensorboard_style_matches(
        self,
    ):
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        container_client.list_blobs.return_value = [
            self._blob(
                "proj/task-1/events.out.tfevents.1700000000.myhost.1.0"
            ),
            self._blob(
                "proj/task-1/events.out.tfevents.1700000100.myhost.2.0"
            ),
        ]
        client = MagicMock()
        runner = _runner(client=client)

        with self.assertRaises(AmbiguousOutputMatchError):
            runner.read_output(_handle(), "events.out.tfevents")
        client.jobs.download.assert_not_called()

    def test_basename_prefix_fallback_only_tried_when_nested_search_is_empty(
        self,
    ):
        # If the nested-suffix search already finds a unique match, the
        # basename-prefix fallback must never run.
        _blob_client, container_client = self._patch_container_client(
            download_blob_side_effect=ResourceNotFoundError("missing")
        )
        exact_name = "proj/task-1/logs/manifest.json"
        container_client.list_blobs.return_value = [self._blob(exact_name)]
        matched_blob_client = MagicMock()
        downloader = MagicMock()
        downloader.readall.return_value = b"suffix-match"
        matched_blob_client.download_blob.return_value = downloader

        def _get_blob_client(name):
            if name == exact_name:
                return matched_blob_client
            bc = MagicMock()
            bc.download_blob.side_effect = ResourceNotFoundError("missing")
            return bc

        container_client.get_blob_client.side_effect = _get_blob_client
        runner = _runner()

        result = runner.read_output(_handle(), "manifest.json")
        self.assertEqual(result, "suffix-match")
        # Exactly one list_blobs call — the nested-suffix search already
        # found a unique match, so the basename-prefix fallback never ran.
        container_client.list_blobs.assert_called_once()


class TestCancel(unittest.TestCase):
    def test_no_op_when_already_terminal(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Completed")
        runner = _runner(client=client)

        runner.cancel(_handle())
        client.jobs.begin_cancel.assert_not_called()

    def test_cancels_when_not_terminal(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        poller = MagicMock()
        client.jobs.begin_cancel.return_value = poller
        runner = _runner(client=client)

        runner.cancel(_handle())
        client.jobs.begin_cancel.assert_called_once_with("haste-exec-1")
        poller.wait.assert_called_once()

    def test_no_op_when_job_not_found(self):
        client = MagicMock()
        client.jobs.get.side_effect = ResourceNotFoundError("not found")
        runner = _runner(client=client)

        runner.cancel(_handle())  # must not raise
        client.jobs.begin_cancel.assert_not_called()

    def test_no_op_when_begin_cancel_reports_not_found(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = ResourceNotFoundError("gone")
        runner = _runner(client=client)

        runner.cancel(_handle())  # must not raise

    def test_no_op_on_conflict_between_check_and_cancel(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = _http_error(409)
        runner = _runner(client=client)

        runner.cancel(_handle())  # must not raise

    def test_raises_job_cancellation_error_on_other_http_error(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = _http_error(500)
        runner = _runner(client=client)

        with self.assertRaises(JobCancellationError):
            runner.cancel(_handle())

    def test_raises_job_cancellation_error_on_network_error(self):
        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = ServiceRequestError("timeout")
        runner = _runner(client=client)

        with self.assertRaises(JobCancellationError):
            runner.cancel(_handle())

    def test_raises_job_cancellation_error_on_validation_exception(self):
        from azure.ai.ml.exceptions import ValidationException

        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = ValidationException(
            message="invalid cancel request",
            no_personal_data_message="invalid cancel request",
        )
        runner = _runner(client=client)

        with self.assertRaises(JobCancellationError):
            runner.cancel(_handle())

    def test_raises_job_cancellation_error_on_job_exception(self):
        from azure.ai.ml.exceptions import JobException

        client = MagicMock()
        client.jobs.get.return_value = _job(status="Running")
        client.jobs.begin_cancel.side_effect = JobException(
            message="cannot cancel this job",
            no_personal_data_message="cannot cancel this job",
        )
        runner = _runner(client=client)

        with self.assertRaises(JobCancellationError):
            runner.cancel(_handle())


class TestFinalize(unittest.TestCase):
    def test_logs_and_does_not_raise(self):
        client = MagicMock()
        runner = _runner(client=client)

        runner.finalize(_handle())  # must not raise
        runner.logger.info.assert_called()

    def test_makes_no_provider_call(self):
        # finalize() has no AML cleanup action — it must never call the
        # provider to look up status or anything else.
        client = MagicMock()
        runner = _runner(client=client)

        runner.finalize(_handle())

        client.jobs.get.assert_not_called()
        client.jobs.download.assert_not_called()
        client.jobs.begin_cancel.assert_not_called()
        client.jobs.create_or_update.assert_not_called()

    def test_a_transient_status_failure_does_not_make_a_no_op_finalize_fail(
        self,
    ):
        # Even a client wired to fail on every call must not make
        # finalize() raise, since finalize() never calls it.
        client = MagicMock()
        client.jobs.get.side_effect = _http_error(500)
        runner = _runner(client=client)

        runner.finalize(_handle())  # must not raise
        client.jobs.get.assert_not_called()

    def test_idempotent_repeated_calls(self):
        client = MagicMock()
        runner = _runner(client=client)

        runner.finalize(_handle())
        runner.finalize(_handle())  # must not raise the second time either
        client.jobs.get.assert_not_called()


class TestGetCapacity(unittest.TestCase):
    def test_unavailable_when_no_compute_configured(self):
        runner = _runner(
            compute_by_workload={
                ComputeWorkload.TRAINING: None,
                ComputeWorkload.INFERENCE: None,
                ComputeWorkload.EMBEDDING: None,
                ComputeWorkload.IMAGERY_PREPARATION: None,
                ComputeWorkload.ARTIFACT_PACKAGING: None,
            }
        )
        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.UNAVAILABLE)
        self.assertEqual(snapshot.backend, ComputeBackend.AZURE_ML)

    def test_unavailable_when_compute_not_found(self):
        client = MagicMock()
        client.compute.get.side_effect = ResourceNotFoundError("missing")
        runner = _runner(client=client)
        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.UNAVAILABLE)

    def test_unknown_when_compute_get_fails(self):
        client = MagicMock()
        client.compute.get.side_effect = _http_error(500)
        runner = _runner(client=client)
        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.UNKNOWN)

    def test_unavailable_when_provisioning_failed(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Failed"
        client.compute.get.return_value = compute
        runner = _runner(client=client)
        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.UNAVAILABLE)

    def test_available_when_a_node_is_idle(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Succeeded"
        client.compute.get.return_value = compute
        idle_node = MagicMock()
        idle_node.current_job_name = None
        busy_node = MagicMock()
        busy_node.current_job_name = "some-other-job"
        client.compute.list_nodes.return_value = [busy_node, idle_node]
        runner = _runner(client=client)

        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.AVAILABLE)

    def test_queueable_when_no_node_is_idle(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Succeeded"
        client.compute.get.return_value = compute
        busy_node = MagicMock()
        busy_node.current_job_name = "some-job"
        client.compute.list_nodes.return_value = [busy_node]
        runner = _runner(client=client)

        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.QUEUEABLE)

    def test_queueable_when_scaled_to_zero_with_no_nodes(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Succeeded"
        client.compute.get.return_value = compute
        client.compute.list_nodes.return_value = []
        runner = _runner(client=client)

        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.QUEUEABLE)

    def test_queueable_when_node_listing_fails(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Succeeded"
        client.compute.get.return_value = compute
        client.compute.list_nodes.side_effect = _http_error(500)
        runner = _runner(client=client)

        snapshot = runner.get_capacity(
            ComputeWorkload.TRAINING, ComputeResources()
        )
        self.assertEqual(snapshot.state, CapacityState.QUEUEABLE)

    def test_target_override_used_for_capacity_check(self):
        client = MagicMock()
        compute = MagicMock()
        compute.provisioning_state = "Succeeded"
        client.compute.get.return_value = compute
        client.compute.list_nodes.return_value = []
        runner = _runner(client=client)

        runner.get_capacity(
            ComputeWorkload.TRAINING,
            ComputeResources(targetOverride="custom-cluster"),
        )
        client.compute.get.assert_called_once_with("custom-cluster")


if __name__ == "__main__":
    unittest.main()
