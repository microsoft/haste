# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the compute/AML sections of ``hastegeo.core.config.Config``
(``get_compute_config``, ``get_aml_config``,
``aml_environment_env_var_name_for_workload``,
``get_aml_environment_reference_for_workload``).

Every test runs with a fully-cleared environment (``patch.dict(...,
clear=True)``) so results depend only on the variables the test itself
sets, not on whatever happens to be defined in the ambient shell.
"""

import unittest
from unittest.mock import patch

from hastegeo.core.config import AML_IDENTITY_MODES, AML_MODES, Config
from hastegeo.core.models.compute import ComputeBackend, ComputeWorkload


def _env(**overrides):
    return patch.dict("os.environ", overrides, clear=True)


class TestGetComputeConfig(unittest.TestCase):
    def test_defaults_to_azure_batch_with_no_env_set(self):
        with _env():
            config = Config.get_compute_config()
        self.assertEqual(config["default_backend"], ComputeBackend.AZURE_BATCH)
        self.assertEqual(config["backend_overrides"], {})
        self.assertTrue(config["follow_on_inherits_backend"])
        self.assertFalse(config["runner_type_alias_used"])

    def test_runner_type_is_a_deprecated_alias_for_the_default(self):
        with _env(RUNNER_TYPE="azure_ml"):
            config = Config.get_compute_config()
        self.assertEqual(config["default_backend"], ComputeBackend.AZURE_ML)
        self.assertTrue(config["runner_type_alias_used"])

    def test_compute_backend_default_takes_precedence_over_runner_type(self):
        with _env(RUNNER_TYPE="azure_ml", COMPUTE_BACKEND_DEFAULT="local"):
            config = Config.get_compute_config()
        self.assertEqual(config["default_backend"], ComputeBackend.LOCAL)
        self.assertFalse(config["runner_type_alias_used"])

    def test_invalid_compute_backend_default_raises(self):
        with _env(COMPUTE_BACKEND_DEFAULT="not-a-backend"):
            with self.assertRaises(ValueError):
                Config.get_compute_config()

    def test_invalid_runner_type_alias_raises(self):
        with _env(RUNNER_TYPE="not-a-backend"):
            with self.assertRaises(ValueError):
                Config.get_compute_config()

    def test_per_workload_overrides_are_parsed(self):
        with _env(
            COMPUTE_BACKEND_TRAINING="azure_ml",
            COMPUTE_BACKEND_IMAGERYPREP="local",
        ):
            config = Config.get_compute_config()
        self.assertEqual(
            config["backend_overrides"],
            {
                ComputeWorkload.TRAINING: ComputeBackend.AZURE_ML,
                ComputeWorkload.IMAGERY_PREPARATION: ComputeBackend.LOCAL,
            },
        )

    def test_invalid_per_workload_override_raises(self):
        with _env(COMPUTE_BACKEND_INFERENCE="bogus"):
            with self.assertRaises(ValueError):
                Config.get_compute_config()

    def test_follow_on_inherits_backend_can_be_disabled(self):
        with _env(COMPUTE_FOLLOW_ON_INHERITS_BACKEND="false"):
            config = Config.get_compute_config()
        self.assertFalse(config["follow_on_inherits_backend"])


class TestGetAmlConfig(unittest.TestCase):
    def test_defaults_are_disabled_and_all_unset(self):
        with _env():
            config = Config.get_aml_config()
        self.assertEqual(config["mode"], "Disabled")
        self.assertIsNone(config["subscription_id"])
        self.assertIsNone(config["resource_group"])
        self.assertIsNone(config["workspace_name"])
        self.assertIsNone(config["datastore_name"])
        self.assertTrue(
            all(v is None for v in config["compute_by_workload"].values())
        )
        self.assertTrue(
            all(v is None for v in config["environment_by_workload"].values())
        )
        self.assertEqual(config["identity_mode"], "user")
        self.assertIsNone(config["managed_identity_id"])
        self.assertEqual(config["experiment_prefix"], "haste")
        self.assertEqual(config["submission_timeout_seconds"], 120)

    def test_invalid_mode_raises(self):
        with _env(AML_MODE="Enabled"):
            with self.assertRaises(ValueError):
                Config.get_aml_config()

    def test_create_mode_is_accepted(self):
        # Accepted for parity with Batch's Create/Existing vocabulary;
        # this adapter (Stage 1) does not distinguish between Create and
        # Existing and does not provision resources for either — both
        # require the same already-existing identifiers.
        with _env(AML_MODE="Create"):
            config = Config.get_aml_config()
        self.assertEqual(config["mode"], "Create")

    def test_documented_modes_are_disabled_create_and_existing(self):
        self.assertEqual(AML_MODES, ("Disabled", "Create", "Existing"))

    def test_all_documented_modes_are_accepted(self):
        for mode in AML_MODES:
            with self.subTest(mode=mode):
                with _env(AML_MODE=mode):
                    config = Config.get_aml_config()
                self.assertEqual(config["mode"], mode)

    def test_reads_core_workspace_settings(self):
        with _env(
            AML_MODE="Existing",
            AML_SUBSCRIPTION_ID="sub-1",
            AML_RESOURCE_GROUP="rg-1",
            AML_WORKSPACE_NAME="ws-1",
            AML_DATASTORE_NAME="ds-1",
        ):
            config = Config.get_aml_config()
        self.assertEqual(config["subscription_id"], "sub-1")
        self.assertEqual(config["resource_group"], "rg-1")
        self.assertEqual(config["workspace_name"], "ws-1")
        self.assertEqual(config["datastore_name"], "ds-1")

    def test_compute_by_workload_reads_each_suffix(self):
        with _env(
            AML_COMPUTE_TRAINING="gpu-a",
            AML_COMPUTE_INFERENCE="gpu-b",
            AML_COMPUTE_EMBEDDING="gpu-c",
            AML_COMPUTE_IMAGERYPREP="cpu-a",
            AML_COMPUTE_ARTIFACTS="cpu-b",
        ):
            config = Config.get_aml_config()
        self.assertEqual(
            config["compute_by_workload"],
            {
                ComputeWorkload.TRAINING: "gpu-a",
                ComputeWorkload.INFERENCE: "gpu-b",
                ComputeWorkload.EMBEDDING: "gpu-c",
                ComputeWorkload.IMAGERY_PREPARATION: "cpu-a",
                ComputeWorkload.ARTIFACT_PACKAGING: "cpu-b",
            },
        )

    def test_environment_by_workload_collapses_to_two_image_families(self):
        with _env(
            AML_ENVIRONMENT_TRAINING="azureml:train-env:3",
            AML_ENVIRONMENT_IMAGERYPREP="azureml:imageryprep-env:2",
        ):
            config = Config.get_aml_config()
        self.assertEqual(
            config["environment_by_workload"],
            {
                ComputeWorkload.TRAINING: "azureml:train-env:3",
                ComputeWorkload.INFERENCE: "azureml:train-env:3",
                ComputeWorkload.EMBEDDING: "azureml:train-env:3",
                ComputeWorkload.IMAGERY_PREPARATION: (
                    "azureml:imageryprep-env:2"
                ),
                ComputeWorkload.ARTIFACT_PACKAGING: (
                    "azureml:imageryprep-env:2"
                ),
            },
        )

    def test_identity_mode_is_lowercased(self):
        with _env(AML_IDENTITY_MODE="MANAGED"):
            config = Config.get_aml_config()
        self.assertEqual(config["identity_mode"], "managed")
        self.assertIn(config["identity_mode"], AML_IDENTITY_MODES)

    def test_managed_identity_id_and_experiment_prefix(self):
        with _env(
            AML_MANAGED_IDENTITY_ID="/subscriptions/x/.../identity",
            AML_EXPERIMENT_PREFIX="myorg",
        ):
            config = Config.get_aml_config()
        self.assertEqual(
            config["managed_identity_id"], "/subscriptions/x/.../identity"
        )
        self.assertEqual(config["experiment_prefix"], "myorg")

    def test_submission_timeout_seconds_is_configurable_and_bounded(self):
        with _env(AML_SUBMISSION_TIMEOUT_SECONDS="300"):
            config = Config.get_aml_config()
        self.assertEqual(config["submission_timeout_seconds"], 300)

        with _env(AML_SUBMISSION_TIMEOUT_SECONDS="0"):
            with self.assertRaises(ValueError):
                Config.get_aml_config()

        with _env(AML_SUBMISSION_TIMEOUT_SECONDS="999999"):
            with self.assertRaises(ValueError):
                Config.get_aml_config()

    def test_never_raises_for_the_all_disabled_default_deployment(self):
        # AML settings are only required when AML_MODE != Disabled or a job
        # explicitly requests azure_ml (data-model.md#configuration-changes)
        # — a Batch-only deployment must never fail here.
        with _env():
            Config.get_aml_config()  # must not raise


class TestAmlEnvironmentEnvVarNameForWorkload(unittest.TestCase):
    def test_training_family_workloads_share_one_setting(self):
        for workload in (
            ComputeWorkload.TRAINING,
            ComputeWorkload.INFERENCE,
            ComputeWorkload.EMBEDDING,
        ):
            with self.subTest(workload=workload):
                self.assertEqual(
                    Config.aml_environment_env_var_name_for_workload(workload),
                    "AML_ENVIRONMENT_TRAINING",
                )

    def test_imageryprep_family_workloads_share_one_setting(self):
        for workload in (
            ComputeWorkload.IMAGERY_PREPARATION,
            ComputeWorkload.ARTIFACT_PACKAGING,
        ):
            with self.subTest(workload=workload):
                self.assertEqual(
                    Config.aml_environment_env_var_name_for_workload(workload),
                    "AML_ENVIRONMENT_IMAGERYPREP",
                )


class TestGetAmlEnvironmentReferenceForWorkload(unittest.TestCase):
    def test_returns_none_when_unset(self):
        with _env():
            self.assertIsNone(
                Config.get_aml_environment_reference_for_workload(
                    ComputeWorkload.TRAINING
                )
            )

    def test_returns_configured_value_for_training_family(self):
        with _env(AML_ENVIRONMENT_TRAINING="azureml:train-env:3"):
            for workload in (
                ComputeWorkload.TRAINING,
                ComputeWorkload.INFERENCE,
                ComputeWorkload.EMBEDDING,
            ):
                self.assertEqual(
                    Config.get_aml_environment_reference_for_workload(
                        workload
                    ),
                    "azureml:train-env:3",
                )

    def test_returns_configured_value_for_imageryprep_family(self):
        with _env(AML_ENVIRONMENT_IMAGERYPREP="azureml:imageryprep-env:2"):
            for workload in (
                ComputeWorkload.IMAGERY_PREPARATION,
                ComputeWorkload.ARTIFACT_PACKAGING,
            ):
                self.assertEqual(
                    Config.get_aml_environment_reference_for_workload(
                        workload
                    ),
                    "azureml:imageryprep-env:2",
                )


if __name__ == "__main__":
    unittest.main()
