# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ``hastegeo.core.utils.compute_specs``.

Covers the shared spec-building plumbing every workload uses: the work
directory contract, HASTE's output prefix/URI, pre-queue task identifiers,
backend-preference resolution and follow-on inheritance, deterministic API
validation, execution-service wiring (per-workload profiles bound to their
compute targets), and the ``ComputeJobState`` → HASTE status mapping.

See spec/features/aml-compute-backend/plan.md Phase 8/9.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    BatchProviderDetail,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeWorkload,
    InputKind,
    OutputPersistenceMode,
)
from hastegeo.core.runners.registry import RunnerRegistry
from hastegeo.core.utils import compute_specs
from hastegeo.core.utils.compute_specs import (
    CONTAINER_CONFIG_WORKDIR_TOKEN,
    JOB_WORKDIR,
    backend_name,
    backend_rejection_message,
    build_execution_service,
    compute_profile,
    container_ref,
    container_resources,
    file_input,
    folder_input,
    follow_on_backend,
    follow_on_backend_for_record,
    handle_log_fields,
    map_state_to_status,
    new_task_id,
    output_prefix,
    output_uri,
    resolve_backend_preference,
    spec_tags,
    validate_backend_request,
    workspace_output,
)
from hastegeo.core.utils.metadata import MetadataUtils

CONTAINER_URL = "https://acct.blob.core.windows.net/data"


class TestWorkdirContract(unittest.TestCase):
    def test_commands_reference_the_canonical_workdir_variable(self):
        # Processor-generated commands must use the application-owned
        # variable, never a provider-specific one.
        self.assertEqual(JOB_WORKDIR, "$HASTE_JOB_WORKDIR")

    def test_generated_config_token_is_the_image_substitution_token(self):
        # The container images substitute this literal inside generated
        # config files (docker/*/scripts/set_dirs.sh), resolving it from
        # HASTE_JOB_WORKDIR first. Nothing expands a shell variable inside
        # a YAML value, so the token — not "$HASTE_JOB_WORKDIR" — is what
        # config files must carry.
        self.assertEqual(
            CONTAINER_CONFIG_WORKDIR_TOKEN, "AZ_BATCH_TASK_WORKING_DIR"
        )


class TestIdentifiers(unittest.TestCase):
    def test_task_id_is_prefixed_and_unique(self):
        first = new_task_id("trn")
        second = new_task_id("trn")
        self.assertTrue(first.startswith("trn-"))
        self.assertNotEqual(first, second)

    def test_task_id_is_a_valid_execution_id(self):
        task_id = new_task_id("img")
        self.assertRegex(task_id, r"^[A-Za-z0-9._-]+$")
        self.assertLessEqual(len(task_id), 64)

    def test_task_id_requires_a_prefix(self):
        with self.assertRaises(ValueError):
            new_task_id("  ")

    def test_output_prefix_is_the_existing_haste_layout(self):
        prefix = output_prefix("proj-1", "trn-9")
        self.assertEqual(
            prefix, f"{MetadataUtils.hash_string('proj-1')}/trn-9"
        )

    def test_output_prefix_requires_both_parts(self):
        with self.assertRaises(ValueError):
            output_prefix("", "trn-9")
        with self.assertRaises(ValueError):
            output_prefix("proj-1", "")

    def test_output_uri_joins_without_duplicate_separators(self):
        self.assertEqual(
            output_uri("https://acct.blob.core.windows.net/data/", "/a/b/"),
            "https://acct.blob.core.windows.net/data/a/b",
        )


class TestInputsAndOutputs(unittest.TestCase):
    def test_file_input_downloads_a_single_file(self):
        item = file_input("https://acct/c/x.tif", "inputs/x.tif")
        self.assertEqual(item.kind, InputKind.FILE)
        self.assertEqual(item.destinationRelativePath, "inputs/x.tif")

    def test_folder_input_stages_a_prefix(self):
        item = folder_input("https://acct/c/hash/trn-1", "staged/trn-1")
        self.assertEqual(item.kind, InputKind.FOLDER)

    def test_live_output_uses_live_mount(self):
        out = workspace_output(
            name="workspace",
            pattern="**/*",
            container_url=CONTAINER_URL,
            prefix="hash/trn-1",
            live=True,
        )
        self.assertEqual(out.persistenceMode, OutputPersistenceMode.LIVE_MOUNT)
        self.assertEqual(out.destinationUri, f"{CONTAINER_URL}/hash/trn-1")

    def test_default_output_uploads_on_completion(self):
        out = workspace_output(
            name="outputs",
            pattern="outputs/*.*",
            container_url=CONTAINER_URL,
            prefix="hash/zip-1",
        )
        self.assertEqual(
            out.persistenceMode, OutputPersistenceMode.UPLOAD_ON_COMPLETION
        )


class TestContainerAndResources(unittest.TestCase):
    def test_environment_reference_comes_from_config_when_available(self):
        runtime = {
            "image": "acr.example.io/train:v1",
            "environment_reference": "haste-training:7",
        }
        ref = container_ref(runtime)
        self.assertEqual(ref.imageReference, "acr.example.io/train:v1")
        self.assertEqual(ref.environmentReference, "haste-training:7")
        self.assertEqual(ref.workingDirectory, ".")

    def test_environment_reference_is_optional(self):
        ref = container_ref(
            {"image": "acr.example.io/train:v1", "environment_reference": None}
        )
        self.assertIsNone(ref.environmentReference)

    def test_resources_carry_accelerator_and_shared_memory(self):
        resources = container_resources(
            {"accelerator": "gpu", "shared_memory_mb": 32768}
        )
        self.assertEqual(resources.accelerator, "gpu")
        self.assertEqual(resources.sharedMemoryMb, 32768)
        self.assertEqual(resources.nodeCount, 1)

    def test_cpu_workloads_request_no_accelerator(self):
        resources = container_resources(
            {"accelerator": None, "shared_memory_mb": None}
        )
        self.assertIsNone(resources.accelerator)
        self.assertIsNone(resources.sharedMemoryMb)

    def test_tags_carry_identifiers_only(self):
        tags = spec_tags(
            workload=ComputeWorkload.TRAINING,
            project_id="proj-1",
            task_id="trn-1",
            image_layer_id="layer-1",
            model_id="42",
        )
        self.assertEqual(tags.project, "proj-1")
        self.assertEqual(tags.task, "trn-1")
        self.assertEqual(tags.workload, ComputeWorkload.TRAINING)


class TestBackendResolution(unittest.TestCase):
    def test_request_preference_wins_over_configuration(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_batch",
                "COMPUTE_BACKEND_TRAINING": "local",
            },
            clear=False,
        ):
            resolved = resolve_backend_preference(
                requested=ComputeBackend.AZURE_ML,
                workload=ComputeWorkload.TRAINING,
                config=Config(),
            )
        self.assertEqual(resolved, ComputeBackend.AZURE_ML)

    def test_workload_override_wins_over_default(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_batch",
                "COMPUTE_BACKEND_TRAINING": "local",
            },
            clear=False,
        ):
            resolved = resolve_backend_preference(
                requested=None,
                workload=ComputeWorkload.TRAINING,
                config=Config(),
            )
        self.assertEqual(resolved, ComputeBackend.LOCAL)

    def test_falls_back_to_the_configured_default(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_BACKEND_DEFAULT": "azure_ml"},
            clear=False,
        ):
            resolved = resolve_backend_preference(
                requested=None,
                workload=ComputeWorkload.ARTIFACT_PACKAGING,
                config=Config(),
            )
        self.assertEqual(resolved, ComputeBackend.AZURE_ML)

    def test_auto_is_passed_through_for_the_router_to_resolve(self):
        resolved = resolve_backend_preference(
            requested=ComputeBackend.AUTO,
            workload=ComputeWorkload.TRAINING,
            config=Config(),
        )
        self.assertEqual(resolved, ComputeBackend.AUTO)


class TestFollowOnInheritance(unittest.TestCase):
    def test_inherits_when_enabled(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true"},
            clear=False,
        ):
            self.assertEqual(
                follow_on_backend(ComputeBackend.AZURE_ML, config=Config()),
                ComputeBackend.AZURE_ML,
            )

    def test_does_not_pin_a_backend_when_disabled(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "false"},
            clear=False,
        ):
            self.assertIsNone(
                follow_on_backend(ComputeBackend.AZURE_ML, config=Config())
            )


class TestBackendRequestValidation(unittest.TestCase):
    def test_unset_backend_is_always_accepted(self):
        self.assertIsNone(
            validate_backend_request(
                None, ComputeWorkload.TRAINING, config=Config()
            )
        )

    def test_azure_ml_rejected_when_disabled(self):
        with patch.dict("os.environ", {"AML_MODE": "Disabled"}, clear=False):
            message = validate_backend_request(
                ComputeBackend.AZURE_ML,
                ComputeWorkload.TRAINING,
                config=Config(),
            )
        self.assertIsNotNone(message)
        self.assertIn("azure_ml", message)

    def test_azure_ml_accepted_when_enabled(self):
        with patch.dict("os.environ", {"AML_MODE": "Existing"}, clear=False):
            self.assertIsNone(
                validate_backend_request(
                    ComputeBackend.AZURE_ML,
                    ComputeWorkload.TRAINING,
                    config=Config(),
                )
            )

    def test_auto_rejected_without_configured_candidates(self):
        with patch.dict(
            "os.environ", {"COMPUTE_AUTO_CANDIDATES_TRAINING": ""}, clear=False
        ):
            message = validate_backend_request(
                ComputeBackend.AUTO,
                ComputeWorkload.TRAINING,
                config=Config(),
            )
        self.assertIsNotNone(message)
        self.assertIn("auto", message)

    def test_auto_accepted_with_configured_candidates(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_AUTO_CANDIDATES_TRAINING": "azure_batch,local"},
            clear=False,
        ):
            self.assertIsNone(
                validate_backend_request(
                    ComputeBackend.AUTO,
                    ComputeWorkload.TRAINING,
                    config=Config(),
                )
            )

    def test_explicit_batch_is_not_rejected(self):
        self.assertIsNone(
            validate_backend_request(
                ComputeBackend.AZURE_BATCH,
                ComputeWorkload.IMAGERY_PREPARATION,
                config=Config(),
            )
        )


class TestBackendRejectionMessage(unittest.TestCase):
    """The API boundary must reject work it can already prove will fail —
    including when the doomed backend comes from configuration rather than
    from the request."""

    def test_accepts_a_workable_default(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_BACKEND_DEFAULT": "azure_batch"},
            clear=False,
        ):
            self.assertIsNone(
                backend_rejection_message(
                    None, ComputeWorkload.TRAINING, config=Config()
                )
            )

    def test_rejects_an_omitted_backend_whose_default_is_disabled(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_ml",
                "AML_MODE": "Disabled",
            },
            clear=False,
        ):
            message = backend_rejection_message(
                None, ComputeWorkload.TRAINING, config=Config()
            )
        self.assertIsNotNone(message)
        self.assertIn("azure_ml", message)

    def test_rejects_a_workload_override_that_cannot_run(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_batch",
                "COMPUTE_BACKEND_ARTIFACTS": "azure_ml",
                "AML_MODE": "Disabled",
            },
            clear=False,
        ):
            message = backend_rejection_message(
                None,
                ComputeWorkload.ARTIFACT_PACKAGING,
                config=Config(),
            )
        self.assertIsNotNone(message)

    def test_rejects_a_defaulted_auto_without_candidates(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "auto",
                "COMPUTE_AUTO_CANDIDATES_EMBEDDING": "",
            },
            clear=False,
        ):
            message = backend_rejection_message(
                None, ComputeWorkload.EMBEDDING, config=Config()
            )
        self.assertIsNotNone(message)
        self.assertIn("auto", message)

    def test_explicit_request_still_wins_over_a_broken_default(self):
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BACKEND_DEFAULT": "azure_ml",
                "AML_MODE": "Disabled",
            },
            clear=False,
        ):
            self.assertIsNone(
                backend_rejection_message(
                    ComputeBackend.AZURE_BATCH,
                    ComputeWorkload.TRAINING,
                    config=Config(),
                )
            )

    def test_malformed_configuration_is_reported_not_raised(self):
        with patch.dict(
            "os.environ",
            {"COMPUTE_BACKEND_DEFAULT": "my-gpu-cluster"},
            clear=False,
        ):
            message = backend_rejection_message(
                None, ComputeWorkload.TRAINING, config=Config()
            )
        self.assertIsNotNone(message)
        self.assertIn("my-gpu-cluster", message)


class TestRecordHelpers(unittest.TestCase):
    def test_backend_name_returns_a_plain_value(self):
        self.assertEqual(backend_name(ComputeBackend.AZURE_ML), "azure_ml")
        self.assertIsNone(backend_name(None))

    def test_follow_on_for_record_reads_the_persisted_backend(self):
        record = SimpleNamespace(computeBackend=ComputeBackend.LOCAL)
        with patch.dict(
            "os.environ",
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "true"},
            clear=False,
        ):
            self.assertEqual(
                follow_on_backend_for_record(record, config=Config()),
                ComputeBackend.LOCAL,
            )

    def test_follow_on_for_record_respects_the_policy(self):
        record = SimpleNamespace(computeBackend=ComputeBackend.LOCAL)
        with patch.dict(
            "os.environ",
            {"COMPUTE_FOLLOW_ON_INHERITS_BACKEND": "false"},
            clear=False,
        ):
            self.assertIsNone(
                follow_on_backend_for_record(record, config=Config())
            )

    def test_follow_on_for_record_without_a_backend(self):
        self.assertIsNone(
            follow_on_backend_for_record(
                SimpleNamespace(computeBackend=None), config=Config()
            )
        )


class TestStatusMapping(unittest.TestCase):
    """User-visible status strings are unchanged; only the mapping from
    the finer-grained provider states is new."""

    def setUp(self):
        self.status = Config().get_status_types()

    def test_succeeded_maps_to_processed(self):
        self.assertEqual(
            map_state_to_status(ComputeJobState.SUCCEEDED),
            self.status.COMPLETED.value,
        )

    def test_failed_maps_to_failed(self):
        self.assertEqual(
            map_state_to_status(ComputeJobState.FAILED),
            self.status.FAILED.value,
        )

    def test_cancelled_maps_to_cancelled(self):
        self.assertEqual(
            map_state_to_status(ComputeJobState.CANCELLED),
            self.status.CANCELLED.value,
        )

    def test_every_in_flight_state_maps_to_in_progress(self):
        for state in (
            ComputeJobState.PENDING,
            ComputeJobState.SUBMITTING,
            ComputeJobState.QUEUED,
            ComputeJobState.PREPARING,
            ComputeJobState.RUNNING,
        ):
            with self.subTest(state=state):
                self.assertEqual(
                    map_state_to_status(state),
                    self.status.IN_PROGRESS.value,
                )

    def test_unknown_state_raises_instead_of_reporting_in_progress(self):
        with self.assertRaises(ValueError):
            map_state_to_status("not-a-state")


class TestHandleLogging(unittest.TestCase):
    def _handle(self):
        return ComputeJobHandle(
            executionId="trn-1",
            requestedBackend=ComputeBackend.AZURE_BATCH,
            selectedBackend=ComputeBackend.AZURE_BATCH,
            backendProfile="training",
            providerJobId="training-pool",
            providerTaskId="trn-1",
            targetId="training-pool",
            outputUri=f"{CONTAINER_URL}/hash/trn-1",
            submittedAt="2026-01-01T00:00:00+00:00",
            routingReason="explicit",
            providerDetail=ComputeProviderDetail(
                discriminator="batch",
                batch=BatchProviderDetail(
                    jobId="training-pool", taskId="trn-1"
                ),
            ),
        )

    def test_log_fields_never_include_urls(self):
        fields = handle_log_fields(self._handle())
        self.assertEqual(fields["executionId"], "trn-1")
        self.assertEqual(fields["backend"], "azure_batch")
        self.assertNotIn("outputUri", fields)
        for value in fields.values():
            self.assertNotIn("https://", str(value))

    def test_missing_handle_is_loggable(self):
        self.assertIsNone(handle_log_fields(None)["executionId"])


class TestExecutionServiceWiring(unittest.TestCase):
    def test_profiles_are_registered_for_every_workload(self):
        service = build_execution_service(Config())
        registry = service._registry

        for workload in ComputeWorkload:
            key = (ComputeBackend.AZURE_BATCH, compute_profile(workload))
            self.assertIn(key, registry._factories)

    def test_a_caller_supplied_registry_is_used_untouched(self):
        # A caller that brings its own registry owns its registrations
        # (fake adapters in tests, custom factories in a deployment);
        # overwriting them would silently swap in real provider adapters.
        registry = RunnerRegistry(Config())
        sentinel = object()

        def _factory():
            return sentinel

        registry.register(
            ComputeBackend.AZURE_BATCH,
            _factory,
            profile=compute_profile(ComputeWorkload.TRAINING),
        )
        service = build_execution_service(Config(), registry=registry)

        self.assertIs(service._registry, registry)
        self.assertIs(
            registry._factories[
                (
                    ComputeBackend.AZURE_BATCH,
                    compute_profile(ComputeWorkload.TRAINING),
                )
            ],
            _factory,
        )
        # No extra profiles are added to a registry the caller owns.
        self.assertEqual(
            set(registry._factories),
            {
                (
                    ComputeBackend.AZURE_BATCH,
                    compute_profile(ComputeWorkload.TRAINING),
                )
            },
        )

    def test_batch_factory_binds_the_workloads_compute_targets(self):
        config = Config()
        service = build_execution_service(config)

        factory = service._registry._factories[
            (
                ComputeBackend.AZURE_BATCH,
                compute_profile(ComputeWorkload.ARTIFACT_PACKAGING),
            )
        ]
        with patch(
            "hastegeo.core.runners.azure_batch.AzureBatchRunner"
        ) as runner_cls:
            factory()

        expected = config.get_compute_runtime_config(
            ComputeWorkload.ARTIFACT_PACKAGING
        )["target_candidates"]
        _, kwargs = runner_cls.call_args
        self.assertEqual(kwargs["candidate_pool_ids"], expected)
        self.assertEqual(kwargs["pool_id"], expected[0])

    def test_gpu_and_cpu_workloads_get_different_targets(self):
        config = Config()
        with patch.dict(
            "os.environ",
            {
                "AZURE_BATCH_TRAINING_POOL_IDS": "h100-pool,t4-pool",
                "AZURE_BATCH_IMAGERYPREP_POOL_IDS": "cpu-pool",
            },
            clear=False,
        ):
            training = config.get_compute_runtime_config(
                ComputeWorkload.TRAINING
            )
            artifacts = config.get_compute_runtime_config(
                ComputeWorkload.ARTIFACT_PACKAGING
            )
        self.assertEqual(
            training["target_candidates"], ["h100-pool", "t4-pool"]
        )
        self.assertEqual(artifacts["target_candidates"], ["cpu-pool"])
        # Artifact packaging must stay CPU-target capable.
        self.assertIsNone(artifacts["accelerator"])
        self.assertEqual(training["accelerator"], "gpu")

    def test_profiles_are_stable_names(self):
        self.assertEqual(
            compute_profile(ComputeWorkload.IMAGERY_PREPARATION),
            "imageryprep",
        )
        self.assertEqual(
            compute_profile(ComputeWorkload.ARTIFACT_PACKAGING), "artifacts"
        )


class TestModuleSurface(unittest.TestCase):
    def test_helper_reads_no_environment_variables_directly(self):
        # Neutral-vs-legacy setting names live in Config only; this module
        # must resolve everything through Config so no processor (and no
        # shared helper) hard-codes a provider setting name.
        with open(compute_specs.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("os.getenv", source)
        self.assertNotIn("os.environ", source)


if __name__ == "__main__":
    unittest.main()
