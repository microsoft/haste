# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the backend-neutral compute models
(``hastegeo.core.models.compute``).

Covers path/URI/tag/environment validation (safe, without false positives),
secret-exclusion on ``ComputeJobSpec``/``ComputeJobHandle``, and legacy
Batch-handle synthesis. See
spec/features/aml-compute-backend/test-plan.md UT-001..UT-008.
"""

import os
import unittest

from hastegeo.core.models.compute import (
    LEGACY_SYNTHESIZED_ROUTING_REASON,
    AzureMlProviderDetail,
    BatchProviderDetail,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeContainerRef,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeOutput,
    ComputeProviderDetail,
    ComputeResources,
    ComputeTags,
    ComputeWorkload,
    InputDeliveryMode,
    InputKind,
    OutputPersistenceMode,
    is_credential_shaped_key,
    is_deployed_environment,
    looks_like_credential,
    synthesize_legacy_batch_handle,
    validate_environment_reference,
    validate_relative_path,
    validate_uri_scheme,
)
from pydantic import ValidationError


def _image_ref(deployed_safe=True):
    if deployed_safe:
        return "acr.example.io/train@sha256:" + ("a1" * 32)
    return "acr.example.io/train:latest"


def _container(**overrides):
    kwargs = dict(imageReference=_image_ref())
    kwargs.update(overrides)
    return ComputeContainerRef(**kwargs)


def _tags(workload=ComputeWorkload.TRAINING, **overrides):
    kwargs = dict(project="proj-1", workload=workload)
    kwargs.update(overrides)
    return ComputeTags(**kwargs)


def _spec(**overrides):
    kwargs = dict(
        executionId="exec-abc-123",
        workload=ComputeWorkload.TRAINING,
        backendPreference=ComputeBackend.AUTO,
        container=_container(),
        command="./run.sh",
        tags=_tags(),
    )
    kwargs.update(overrides)
    return ComputeJobSpec(**kwargs)


def _handle(**overrides):
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


class TestValidateRelativePath(unittest.TestCase):
    """UT-001: destination path with '../' or leading '/' must be rejected;
    ordinary relative paths (including glob patterns) must not be."""

    def test_rejects_leading_slash(self):
        with self.assertRaises(ValueError):
            validate_relative_path("/etc/passwd", field_name="x")

    def test_rejects_parent_traversal_segment(self):
        with self.assertRaises(ValueError):
            validate_relative_path("a/../b", field_name="x")

    def test_rejects_bare_parent_traversal(self):
        with self.assertRaises(ValueError):
            validate_relative_path("..", field_name="x")

    def test_rejects_windows_drive_absolute_path(self):
        with self.assertRaises(ValueError):
            validate_relative_path("C:/Windows/System32", field_name="x")

    def test_rejects_backslash_separators(self):
        with self.assertRaises(ValueError):
            validate_relative_path("a\\b", field_name="x")

    def test_rejects_empty_segment(self):
        with self.assertRaises(ValueError):
            validate_relative_path("a//b", field_name="x")

    def test_rejects_empty_value(self):
        with self.assertRaises(ValueError):
            validate_relative_path("", field_name="x")

    def test_accepts_plain_relative_path(self):
        self.assertEqual(
            validate_relative_path("inputs/scene.tif", field_name="x"),
            "inputs/scene.tif",
        )

    def test_accepts_glob_pattern_without_false_positive(self):
        # Output patterns are globs, not literal paths; '*'/'**' segments
        # must not be mistaken for traversal.
        self.assertEqual(
            validate_relative_path("checkpoints/**/*.pt", field_name="x"),
            "checkpoints/**/*.pt",
        )

    def test_accepts_dot_segment_for_workspace_root(self):
        self.assertEqual(validate_relative_path(".", field_name="x"), ".")


class TestValidateUriScheme(unittest.TestCase):
    """UT-003: unrecognized URI schemes on input/output must be rejected."""

    def test_accepts_https(self):
        validate_uri_scheme(
            "https://acct.blob.core.windows.net/c/f.tif", field_name="x"
        )

    def test_accepts_http_for_local_azurite(self):
        # Local dev's Azurite emulator is plain http; must not be a false
        # positive rejection.
        validate_uri_scheme(
            "http://azurite:10000/devstoreaccount1/c/f.tif", field_name="x"
        )

    def test_accepts_s3(self):
        validate_uri_scheme("s3://bucket/key.tif", field_name="x")

    def test_accepts_abfss(self):
        validate_uri_scheme(
            "abfss://fs@acct.dfs.core.windows.net/path", field_name="x"
        )

    def test_accepts_azureml_datastore_uri(self):
        validate_uri_scheme(
            "azureml://datastores/hastestore/paths/out/model.pt",
            field_name="x",
        )

    def test_accepts_adl_uri(self):
        validate_uri_scheme(
            "adl://myaccount.azuredatalakestore.net/path/scene.tif",
            field_name="x",
        )

    def test_rejects_unrecognized_scheme(self):
        with self.assertRaises(ValueError):
            validate_uri_scheme("ftp://host/path", field_name="x")

    def test_rejects_javascript_scheme(self):
        with self.assertRaises(ValueError):
            validate_uri_scheme("javascript:alert(1)", field_name="x")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_uri_scheme("", field_name="x")

    def test_rejects_missing_host(self):
        with self.assertRaises(ValueError):
            validate_uri_scheme("https:///path", field_name="x")


class TestLooksLikeCredential(unittest.TestCase):
    """UT-005: credential-shaped strings must be detected without flagging
    ordinary identifiers (image digests, model names, etc)."""

    def test_detects_sas_query_string(self):
        self.assertTrue(
            looks_like_credential(
                "https://a.blob.core.windows.net/c/f?sv=2020-01-01&"
                "se=2026-01-01&sig=abcdef123456"
            )
        )

    def test_detects_connection_string_account_key(self):
        self.assertTrue(
            looks_like_credential(
                "DefaultEndpointsProtocol=https;AccountName=x;"
                "AccountKey=abc123def456=="
            )
        )

    def test_detects_bearer_token(self):
        self.assertTrue(
            looks_like_credential(
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abc"
            )
        )

    def test_detects_jwt_shape(self):
        self.assertTrue(
            looks_like_credential(
                # pragma: allowlist nextline secret
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGhpc2lzdGVzdA"
            )
        )

    def test_detects_password_kv_pair(self):
        # pragma: allowlist nextline secret
        self.assertTrue(looks_like_credential("password=hunter2secretvalue"))

    def test_no_false_positive_on_image_digest(self):
        self.assertFalse(looks_like_credential(_image_ref()))

    def test_no_false_positive_on_plain_url(self):
        self.assertFalse(
            looks_like_credential("https://acct.blob.core.windows.net/c/f.tif")
        )

    def test_no_false_positive_on_ordinary_text(self):
        self.assertFalse(looks_like_credential("hurricane-2026-imagery-run-3"))

    def test_no_false_positive_on_sig_without_sas_hints(self):
        # 'sig=' alone (no sv/se/sp/... companion) is not enough to flag —
        # avoids rejecting an unrelated query string that happens to use
        # the word "sig".
        self.assertFalse(looks_like_credential("https://x/y?sig=notasastoken"))

    def test_empty_and_none_are_not_credentials(self):
        self.assertFalse(looks_like_credential(""))
        self.assertFalse(looks_like_credential(None))


class TestIsCredentialShapedKey(unittest.TestCase):
    def test_matches_normalized_denylist_entries(self):
        self.assertTrue(is_credential_shaped_key("API_KEY"))
        self.assertTrue(is_credential_shaped_key("api-key"))
        self.assertTrue(is_credential_shaped_key("AccountKey"))
        self.assertTrue(is_credential_shaped_key("TOKEN"))

    def test_no_false_positive_on_unrelated_key_containing_substring(self):
        # "MODEL_TOKEN_LIMIT" normalizes to "modeltokenlimit", which is not
        # in the denylist even though it contains "token".
        self.assertFalse(is_credential_shaped_key("MODEL_TOKEN_LIMIT"))
        self.assertFalse(is_credential_shaped_key("PROJECT_NAME"))


class TestComputeContainerRefImageReference(unittest.TestCase):
    """UT-004: mutable image reference (':latest') must be rejected in a
    deployed profile; dev/test may use tags."""

    def test_tag_reference_allowed_in_dev(self):
        self.assertEqual(os.getenv("env", "dev"), "dev")
        ref = _container(imageReference=_image_ref(deployed_safe=False))
        self.assertTrue(ref.imageReference.endswith(":latest"))

    def test_tag_reference_rejected_when_deployed(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            self.assertTrue(is_deployed_environment())
            with self.assertRaises(ValidationError):
                _container(imageReference=_image_ref(deployed_safe=False))
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original

    def test_digest_reference_allowed_when_deployed(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            ref = _container(imageReference=_image_ref(deployed_safe=True))
            self.assertIn("@sha256:", ref.imageReference)
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original

    def test_empty_image_reference_always_rejected(self):
        with self.assertRaises(ValidationError):
            _container(imageReference="   ")

    def test_versioned_non_digest_tag_allowed_when_deployed(self):
        """Batch-compatibility: a versioned (non-':latest', non-digest)
        tag must remain usable in deployed environments — only the
        literal ':latest' tag is rejected, not every non-digest tag."""
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            ref = _container(imageReference="acr.example.io/train:v1.2.3")
            self.assertEqual(ref.imageReference, "acr.example.io/train:v1.2.3")
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original

    def test_latest_tag_rejected_case_insensitively_when_deployed(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            with self.assertRaises(ValidationError):
                _container(imageReference="acr.example.io/train:LATEST")
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original


class TestValidateEnvironmentReference(unittest.TestCase):
    """AML-specific: ``environmentReference`` (the resolved AML environment
    *version*) enforces its own stricter, immutable-version rule
    independent of ``imageReference``'s more permissive Batch-compatible
    rule."""

    def test_none_allowed_everywhere(self):
        self.assertIsNone(validate_environment_reference(None))

    def test_versioned_reference_allowed_in_dev(self):
        self.assertEqual(os.getenv("env", "dev"), "dev")
        self.assertEqual(
            validate_environment_reference("haste-training-env:12"),
            "haste-training-env:12",
        )

    def test_latest_alias_rejected_when_deployed(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            with self.assertRaises(ValueError):
                validate_environment_reference("haste-training-env:latest")
            with self.assertRaises(ValueError):
                validate_environment_reference("haste-training-env@latest")
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original

    def test_versioned_reference_allowed_when_deployed(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            self.assertEqual(
                validate_environment_reference("haste-training-env:12"),
                "haste-training-env:12",
            )
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            validate_environment_reference("   ")

    def test_container_ref_applies_environment_reference_validation(self):
        original = os.environ.get("env")
        os.environ["env"] = "prod"
        try:
            with self.assertRaises(ValidationError):
                _container(
                    imageReference=_image_ref(deployed_safe=True),
                    environmentReference="haste-training-env:latest",
                )
            ref = _container(
                imageReference=_image_ref(deployed_safe=True),
                environmentReference="haste-training-env:12",
            )
            self.assertEqual(ref.environmentReference, "haste-training-env:12")
        finally:
            if original is None:
                os.environ.pop("env", None)
            else:
                os.environ["env"] = original


class TestComputeJobSpecValidation(unittest.TestCase):
    def test_valid_spec_round_trips(self):
        spec = _spec()
        payload = spec.model_dump()
        restored = ComputeJobSpec(**payload)
        self.assertEqual(restored.executionId, spec.executionId)

    def test_rejects_input_destination_traversal(self):
        with self.assertRaises(ValidationError):
            _spec(
                inputs=[
                    ComputeInput(
                        sourceUri="https://a.blob.core.windows.net/c/f.tif",
                        kind=InputKind.FILE,
                        destinationRelativePath="../../etc/passwd",
                    )
                ]
            )

    def test_rejects_output_pattern_outside_workspace(self):
        """UT-002: an output pattern that resolves outside the workspace
        (leading '/' or '..') must be rejected."""
        with self.assertRaises(ValidationError):
            _spec(
                outputs=[
                    ComputeOutput(
                        name="ckpt",
                        sourceRelativePattern="../outside/*.pt",
                        destinationUri="https://a.blob.core.windows.net/c/out/",
                    )
                ]
            )

    def test_rejects_unrecognized_input_scheme(self):
        with self.assertRaises(ValidationError):
            _spec(
                inputs=[
                    ComputeInput(
                        sourceUri="ftp://host/scene.tif",
                        kind=InputKind.FILE,
                        destinationRelativePath="in/scene.tif",
                    )
                ]
            )

    def test_accepts_valid_input_and_output(self):
        spec = _spec(
            inputs=[
                ComputeInput(
                    sourceUri="https://a.blob.core.windows.net/c/f.tif",
                    kind=InputKind.FILE,
                    destinationRelativePath="in/f.tif",
                    deliveryMode=InputDeliveryMode.DOWNLOAD,
                )
            ],
            outputs=[
                ComputeOutput(
                    name="ckpt",
                    sourceRelativePattern="out/*.pt",
                    destinationUri="https://a.blob.core.windows.net/c/out/",
                    persistenceMode=OutputPersistenceMode.LIVE_MOUNT,
                )
            ],
        )
        self.assertEqual(len(spec.inputs), 1)
        self.assertEqual(len(spec.outputs), 1)

    def test_rejects_credential_shaped_environment_value(self):
        """UT-005: credential-shaped string in environment must be
        rejected at construction."""
        with self.assertRaises(ValidationError):
            _spec(
                environment={
                    "STORAGE_URL": (
                        "https://a.blob.core.windows.net/c/f?sv=2020-01-01"
                        "&se=2026-01-01&sig=deadbeef"
                    )
                }
            )

    def test_rejects_credential_shaped_environment_key(self):
        with self.assertRaises(ValidationError):
            # pragma: allowlist nextline secret
            _spec(environment={"AWS_SECRET_ACCESS_KEY": "not-a-real-value"})

    def test_accepts_ordinary_environment(self):
        spec = _spec(environment={"MODEL_EPOCHS": "50", "RUN_NAME": "r1"})
        self.assertEqual(spec.environment["MODEL_EPOCHS"], "50")

    def test_rejects_credential_shaped_tag_value(self):
        with self.assertRaises(ValidationError):
            _spec(
                tags=_tags(
                    model="Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmno.pqrstuv"
                )
            )

    def test_rejects_tags_workload_mismatch(self):
        with self.assertRaises(ValidationError):
            _spec(
                workload=ComputeWorkload.TRAINING,
                tags=_tags(workload=ComputeWorkload.INFERENCE),
            )

    def test_rejects_invalid_execution_id_characters(self):
        with self.assertRaises(ValidationError):
            _spec(executionId="exec with spaces/and/slashes")

    def test_rejects_unknown_extra_field(self):
        payload = _spec().model_dump()
        payload["unexpectedField"] = "nope"
        with self.assertRaises(ValidationError):
            ComputeJobSpec(**payload)


class TestComputeResources(unittest.TestCase):
    def test_defaults(self):
        resources = ComputeResources()
        self.assertEqual(resources.nodeCount, 1)
        self.assertFalse(resources.allowSpot)

    def test_rejects_zero_node_count(self):
        with self.assertRaises(ValidationError):
            ComputeResources(nodeCount=0)


class TestCapacitySnapshot(unittest.TestCase):
    def test_rejects_auto_backend(self):
        with self.assertRaises(ValidationError):
            CapacitySnapshot(
                backend=ComputeBackend.AUTO,
                workload=ComputeWorkload.TRAINING,
                state=CapacityState.AVAILABLE,
            )

    def test_accepts_concrete_backend(self):
        snapshot = CapacitySnapshot(
            backend=ComputeBackend.AZURE_BATCH,
            workload=ComputeWorkload.TRAINING,
            state=CapacityState.AVAILABLE,
        )
        self.assertEqual(snapshot.state, CapacityState.AVAILABLE)


class TestComputeJobHandle(unittest.TestCase):
    """UT-006: handle round-trip must never surface a token/key/SAS field."""

    def test_valid_handle_round_trips_with_no_secret_fields(self):
        handle = _handle()
        payload = handle.model_dump()
        serialized = str(payload)
        for forbidden in (
            "AccountKey",
            "sig=",
            "Bearer ",
            "password=",
            "SharedAccessSignature",
        ):
            self.assertNotIn(forbidden, serialized)
        restored = ComputeJobHandle(**payload)
        self.assertEqual(restored.providerJobId, handle.providerJobId)

    def test_rejects_auto_as_selected_backend(self):
        with self.assertRaises(ValidationError):
            _handle(
                requestedBackend=ComputeBackend.AUTO,
                selectedBackend=ComputeBackend.AUTO,
            )

    def test_rejects_signed_output_uri(self):
        with self.assertRaises(ValidationError):
            _handle(
                outputUri=(
                    "https://acct.blob.core.windows.net/c/out/f.tif?"
                    "sv=2020-01-01&se=2026-01-01&sig=deadbeef"
                )
            )

    def test_rejects_credential_shaped_provider_job_id(self):
        with self.assertRaises(ValidationError):
            _handle(
                providerJobId="Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmno.pqrstuv"
            )

    def test_rejects_provider_detail_discriminator_mismatch(self):
        with self.assertRaises(ValidationError):
            _handle(
                selectedBackend=ComputeBackend.AZURE_ML,
                providerDetail=ComputeProviderDetail(
                    discriminator="batch",
                    batch=BatchProviderDetail(jobId="job-1", taskId="task-1"),
                ),
            )

    def test_rejects_multiple_populated_provider_slots(self):
        with self.assertRaises(ValidationError):
            ComputeProviderDetail(
                discriminator="batch",
                batch=BatchProviderDetail(jobId="job-1", taskId="task-1"),
                azureMl=AzureMlProviderDetail(jobName="j", workspace="w"),
            )

    def test_rejects_unknown_extra_field(self):
        payload = _handle().model_dump()
        payload["accessToken"] = "should-not-be-accepted"
        with self.assertRaises(ValidationError):
            ComputeJobHandle(**payload)


class TestLegacyBatchHandleSynthesis(unittest.TestCase):
    """UT-007: a legacy TrainingJob-shaped record with only jobId/taskId
    synthesizes a Batch ComputeJobHandle on load."""

    def test_synthesizes_batch_handle(self):
        handle = synthesize_legacy_batch_handle(
            job_id="job-42",
            task_id="task-7",
            output_uri="https://acct.blob.core.windows.net/c/out/",
        )
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(handle.requestedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(
            handle.routingReason, LEGACY_SYNTHESIZED_ROUTING_REASON
        )
        self.assertEqual(handle.providerDetail.discriminator, "batch")
        self.assertEqual(handle.providerDetail.batch.jobId, "job-42")
        self.assertEqual(handle.providerDetail.batch.taskId, "task-7")
        self.assertEqual(handle.providerJobId, "job-42")
        self.assertEqual(handle.providerTaskId, "task-7")

    def test_requires_job_id(self):
        with self.assertRaises(ValueError):
            synthesize_legacy_batch_handle(
                job_id="", task_id="task-7", output_uri="https://a/b"
            )

    def test_requires_task_id(self):
        with self.assertRaises(ValueError):
            synthesize_legacy_batch_handle(
                job_id="job-42", task_id="", output_uri="https://a/b"
            )


if __name__ == "__main__":
    unittest.main()
