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
from hastegeo.core.runners.azure_batch import AzureBatchJob, AzureBatchRunner
from hastegeo.core.utils.batch_config import (
    BatchConfigurationError,
    has_placeholder,
    resolve_job_id,
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

    assert job.create_job("job-1") == "job-1"

    job.batch_client.job.patch.assert_called_once()
    patched = job.batch_client.job.patch.call_args[0][1]
    assert patched.pool_info.pool_id == "selected-pool"


def test_create_job_does_not_rebind_when_pool_already_matches():
    job = _job(pool_id="selected-pool")
    job.batch_client.job.get.return_value = _existing_job("selected-pool")

    assert job.create_job("job-1") == "job-1"

    job.batch_client.job.patch.assert_not_called()


def test_create_job_falls_back_to_pool_scoped_job_when_rebinding_refused():
    # Batch refuses to re-point a job that still has active tasks. Rather than
    # failing the submission, fall back to a job scoped to the selected pool.
    job = _job(pool_id="t4-pool")
    error = BatchErrorException(lambda *a, **k: None, MagicMock())
    error.error = MagicMock(code="OperationInvalidForCurrentState")
    job.batch_client.job.patch.side_effect = error

    not_found = BatchErrorException(lambda *a, **k: None, MagicMock())
    not_found.error = MagicMock(code="JobNotFound")
    job.batch_client.job.get.side_effect = [
        _existing_job("h100-pool"),
        not_found,
    ]

    used = job.create_job("h100-pool")

    assert used == "t4-pool"
    added = job.batch_client.job.add.call_args[0][0]
    assert added.id == "t4-pool"
    assert added.pool_info.pool_id == "t4-pool"


def test_create_job_reuses_existing_pool_scoped_job_on_fallback():
    job = _job(pool_id="t4-pool")
    error = BatchErrorException(lambda *a, **k: None, MagicMock())
    error.error = MagicMock(code="OperationInvalidForCurrentState")
    job.batch_client.job.patch.side_effect = error
    job.batch_client.job.get.side_effect = [
        _existing_job("h100-pool"),
        _existing_job("t4-pool"),
    ]

    assert job.create_job("h100-pool") == "t4-pool"
    job.batch_client.job.add.assert_not_called()


def test_resolve_job_id_follows_selected_pool_by_default_convention():
    # Job ids default to the pool id, so track whichever pool was selected
    # rather than doubling the pool id up.
    assert (
        resolve_job_id("h100-pool", "t4-pool", ["h100-pool", "t4-pool"])
        == "t4-pool"
    )


def test_resolve_job_id_leaves_single_pool_environments_untouched():
    # No spillover is possible, so an existing custom job id is not renamed.
    assert resolve_job_id("my-job", "only-pool", ["only-pool"]) == "my-job"
    assert resolve_job_id("my-job", "only-pool", []) == "my-job"


def test_resolve_job_id_scopes_custom_job_ids_when_routing():
    assert (
        resolve_job_id("my-job", "t4-pool", ["h100-pool", "t4-pool"])
        == "my-job-t4-pool"
    )


def test_resolve_job_id_respects_the_64_character_batch_limit():
    base = "b" * 60
    pool = "p" * 20
    resolved = resolve_job_id(base, pool, ["other-pool", pool])
    assert len(resolved) <= 64
    assert resolved.endswith(pool)


def test_resolve_job_id_keeps_different_pools_distinct_when_truncating():
    # Truncating the base rather than the pool is what keeps two pools from
    # collapsing onto the same job id.
    base = "b" * 60
    a = resolve_job_id(base, "pool-aaaaaaaaaaaaaaaaaaaa", ["x", "y"])
    b = resolve_job_id(base, "pool-bbbbbbbbbbbbbbbbbbbb", ["x", "y"])
    assert a != b
    assert len(a) <= 64 and len(b) <= 64


def test_spillover_to_a_second_pool_uses_a_separate_job(monkeypatch):
    # Regression: a task that spills over to another pool must not collide with
    # the job the first task created on the preferred pool.
    monkeypatch.setenv("AZURE_BATCH_ACCOUNT_NAME", "acct")
    monkeypatch.setenv("AZURE_BATCH_ACCOUNT_KEY", "key")
    monkeypatch.setenv(
        "AZURE_BATCH_URL", "https://acct.westus2.batch.azure.com"
    )
    monkeypatch.setenv(
        "AZURE_BATCH_OUTPUT_CONTAINER_URL",
        "https://sa.blob.core.windows.net/data",
    )
    monkeypatch.setenv("AZURE_BATCH_MANAGE_POOLS", "false")
    monkeypatch.setenv("AZURE_BATCH_IMAGERYPREP_POOL_ID", "h100-pool")

    runner = AzureBatchRunner(
        pool_id="h100-pool", candidate_pool_ids=["h100-pool", "t4-pool"]
    )
    runner.batch_cluster = MagicMock()
    runner.batch_cluster.select_pool.return_value = "t4-pool"
    runner.batch_cluster.create_job.side_effect = lambda jid: jid

    job_id, _ = runner.add_task(
        job_id="h100-pool",
        task_id="img-1",
        image_name="acr.azurecr.io/img:1",
        command="run",
        arguments=[],
        output_container_url="https://sa.blob.core.windows.net/data",
    )

    assert job_id == "t4-pool"
    runner.batch_cluster.create_job.assert_called_once_with("t4-pool")
