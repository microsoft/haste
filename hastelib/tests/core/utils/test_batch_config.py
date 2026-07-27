# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for Azure Batch application-setting resolution + validation.

Covers the drift between the settings the code reads and the settings the
deploy paths emit:
- the AZURE_BATCH_REGISTRY_SERVER rename (with legacy fallback + normalization),
- fail-fast validation of unresolved ``<placeholder>`` defaults,
- rebinding a reused Batch job that is pinned to a stale pool.
"""

from unittest.mock import MagicMock

import pytest
from azure.batch.models import BatchErrorException, JobState
from hastegeo.core.config import REGISTRY_SERVER_PLACEHOLDER, Config
from hastegeo.core.runners.azure_batch import AzureBatchJob
from hastegeo.core.utils.batch_config import (
    BatchConfigurationError,
    BatchJobPoolMismatchError,
    has_placeholder,
    validate_batch_config,
)

REGISTRY_ENV = "AZURE_BATCH_REGISTRY_SERVER"
LEGACY_REGISTRY_ENV = "AZURE_BATCH_REGISTRY_SERVER_URL"


def _registry_server(monkeypatch, new=None, legacy=None):
    for name, value in ((REGISTRY_ENV, new), (LEGACY_REGISTRY_ENV, legacy)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return Config().get_azure_batch_config()["registry_server"]


def test_registry_server_uses_canonical_setting(monkeypatch):
    assert _registry_server(monkeypatch, new="acr.azurecr.io") == (
        "acr.azurecr.io"
    )


def test_registry_server_falls_back_to_legacy_setting(monkeypatch):
    # Environments provisioned before the rename only have the _URL name.
    assert _registry_server(monkeypatch, legacy="https://acr.azurecr.io") == (
        "acr.azurecr.io"
    )


def test_registry_server_prefers_canonical_over_legacy(monkeypatch):
    resolved = _registry_server(
        monkeypatch, new="new.azurecr.io", legacy="https://old.azurecr.io"
    )
    assert resolved == "new.azurecr.io"


def test_registry_server_strips_scheme_and_trailing_slash(monkeypatch):
    # The Batch SDK wants a bare login server, but the app setting is often a
    # URL -- normalize either shape.
    assert _registry_server(monkeypatch, new="https://acr.azurecr.io/") == (
        "acr.azurecr.io"
    )


def test_registry_server_falls_back_to_placeholder(monkeypatch):
    assert _registry_server(monkeypatch) == REGISTRY_SERVER_PLACEHOLDER


def test_has_placeholder_detects_unresolved_defaults():
    assert has_placeholder("<registry-name>.azurecr.io")
    assert not has_placeholder("acr.azurecr.io")
    assert not has_placeholder(None)


def _configured(**overrides):
    config = {
        "account_name": "acct",
        "batch_url": "https://acct.westus2.batch.azure.com",
        "output_container_url": "https://sa.blob.core.windows.net/data",
        "registry_server": "acr.azurecr.io",
        "registry_image": "acr.azurecr.io/hastetraining:1",
        "user_assigned_identity_resource_id": "/subscriptions/x/umi",
    }
    config.update(overrides)
    return config


def test_validate_passes_on_fully_configured_block():
    validate_batch_config(_configured(), manage_pools=True)


def test_validate_raises_and_names_the_missing_setting():
    config = _configured(registry_server=REGISTRY_SERVER_PLACEHOLDER)
    with pytest.raises(BatchConfigurationError) as excinfo:
        validate_batch_config(config, manage_pools=True)
    assert REGISTRY_ENV in str(excinfo.value)


def test_validate_skips_pool_settings_when_not_managing_pools():
    # Pre-created/autoscale pools never read the registry settings, so an
    # unresolved value there must not block submission.
    config = _configured(registry_server=REGISTRY_SERVER_PLACEHOLDER)
    validate_batch_config(config, manage_pools=False)


def test_validate_still_requires_core_settings_without_pool_management():
    config = _configured(account_name="<batch-account-name>")
    with pytest.raises(BatchConfigurationError) as excinfo:
        validate_batch_config(config, manage_pools=False)
    assert "AZURE_BATCH_ACCOUNT_NAME" in str(excinfo.value)


def test_validate_reads_manage_pools_from_the_config_block():
    config = _configured(
        registry_server=REGISTRY_SERVER_PLACEHOLDER, manage_pools=False
    )
    validate_batch_config(config)


def _job(pool_id="selected-pool"):
    job = AzureBatchJob(
        account_name="acct",  # pragma: allowlist secret
        account_key="key",  # pragma: allowlist secret
        batch_url="https://acct.westus2.batch.azure.com",
        pool_id=pool_id,
        user_assigned_identity_resource_id="/subscriptions/x/umi",
        manage_pools=False,
    )
    job.batch_client = MagicMock()
    return job


def _existing_job(bound_pool, state=JobState.active):
    existing = MagicMock()
    existing.id = "job-1"
    existing.state = state
    existing.pool_info.pool_id = bound_pool
    return existing


def test_create_job_rebinds_a_job_pinned_to_a_stale_pool():
    job = _job(pool_id="selected-pool")
    job.batch_client.job.get.return_value = _existing_job("deleted-pool")

    job.create_job("job-1")

    job.batch_client.job.patch.assert_called_once()
    patched = job.batch_client.job.patch.call_args[0][1]
    assert patched.pool_info.pool_id == "selected-pool"


def test_create_job_does_not_rebind_when_pool_already_matches():
    job = _job(pool_id="selected-pool")
    job.batch_client.job.get.return_value = _existing_job("selected-pool")

    job.create_job("job-1")

    job.batch_client.job.patch.assert_not_called()


def test_create_job_raises_when_rebinding_is_refused():
    job = _job(pool_id="selected-pool")
    job.batch_client.job.get.return_value = _existing_job("deleted-pool")
    error = BatchErrorException(lambda *a, **k: None, MagicMock())
    error.error = MagicMock(code="JobStateInvalid")
    job.batch_client.job.patch.side_effect = error

    with pytest.raises(BatchJobPoolMismatchError):
        job.create_job("job-1")
