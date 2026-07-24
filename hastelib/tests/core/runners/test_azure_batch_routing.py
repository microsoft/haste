# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for v2.1.0 capacity-aware pool routing + per-job SAS toggle.

Covers the pure decision logic (no live Batch/Storage calls):
- config candidate pool-id lists + SAS/manage flags,
- AzureBatchJob.select_pool (single, spillover-to-idle, preferred fallback),
- the SAS-vs-identity blob-credential toggle.
"""

from unittest.mock import MagicMock

from azure.batch.models import ComputeNodeIdentityReference, ComputeNodeState
from hastegeo.core.config import Config
from hastegeo.core.runners.azure_batch import AzureBatchJob


def _job(use_sas=False, manage_pools=True):
    job = AzureBatchJob(
        account_name="acct",  # pragma: allowlist secret
        account_key="key",  # pragma: allowlist secret
        batch_url="https://acct.westus2.batch.azure.com",  # pragma: allowlist secret
        pool_id="default-pool",
        user_assigned_identity_resource_id="/subscriptions/x/umi",
        use_sas=use_sas,
        manage_pools=manage_pools,
    )
    job.batch_client = MagicMock()
    return job


def _pool(dedicated=0, lowpri=0):
    m = MagicMock()
    m.current_dedicated_nodes = dedicated
    m.current_low_priority_nodes = lowpri
    return m


def _node(state):
    m = MagicMock()
    m.state = state
    return m


def test_select_pool_single_candidate_makes_no_api_calls():
    job = _job()
    assert job.select_pool(["only-pool"]) == "only-pool"
    job.batch_client.pool.get.assert_not_called()


def test_select_pool_empty_falls_back_to_bound_pool():
    job = _job()
    assert job.select_pool([]) == "default-pool"


def test_select_pool_spills_over_to_pool_with_idle_node():
    job = _job()
    # h100 has a node but it's running (busy); t4 has an idle node.
    job.batch_client.pool.get.side_effect = lambda pid: (
        _pool(dedicated=1) if pid == "h100" else _pool(lowpri=1)
    )
    job.batch_client.compute_node.list.side_effect = lambda pid: (
        [_node(ComputeNodeState.running)]
        if pid == "h100"
        else [_node(ComputeNodeState.idle)]
    )
    assert job.select_pool(["h100", "t4"]) == "t4"


def test_select_pool_prefers_first_candidate_with_idle_node():
    job = _job()
    job.batch_client.pool.get.side_effect = lambda pid: _pool(dedicated=1)
    job.batch_client.compute_node.list.side_effect = lambda pid: [
        _node(ComputeNodeState.idle)
    ]
    assert job.select_pool(["h100", "t4"]) == "h100"


def test_select_pool_falls_back_to_preferred_when_none_idle():
    job = _job()
    # Both pools empty (0 nodes): nothing idle -> preferred first candidate,
    # which will scale up / queue.
    job.batch_client.pool.get.side_effect = lambda pid: _pool()
    assert job.select_pool(["h100", "t4"]) == "h100"


def test_blob_identity_uses_pool_identity_in_legacy_mode():
    job = _job(use_sas=False)
    ident = job._blob_identity()
    assert isinstance(ident, ComputeNodeIdentityReference)
    # legacy mode leaves URLs untouched (no SAS)
    assert job._maybe_sas("https://a.blob/c", "rl") == "https://a.blob/c"


def test_blob_identity_none_and_sas_applied_in_sas_mode():
    job = _job(use_sas=True)
    assert job._blob_identity() is None
    job._sas_url = MagicMock(return_value="https://a.blob/c?sig=xyz")
    assert (
        job._maybe_sas("https://a.blob/c", "rl") == "https://a.blob/c?sig=xyz"
    )
    job._sas_url.assert_called_once_with("https://a.blob/c", "rl")


def test_maybe_sas_noop_on_empty_url():
    job = _job(use_sas=True)
    assert job._maybe_sas(None, "rl") is None


def test_config_candidate_pool_lists_and_flags(monkeypatch):
    monkeypatch.setenv("AZURE_BATCH_TRAINING_POOL_ID", "single-train")
    monkeypatch.setenv("AZURE_BATCH_IMAGERYPREP_POOL_ID", "single-prep")
    monkeypatch.setenv("AZURE_BATCH_TRAINING_POOL_IDS", "h100-pool, t4-pool")
    monkeypatch.delenv("AZURE_BATCH_INFERENCE_POOL_IDS", raising=False)
    monkeypatch.delenv("AZURE_BATCH_IMAGERYPREP_POOL_IDS", raising=False)
    monkeypatch.setenv("AZURE_BATCH_USE_SAS", "true")
    monkeypatch.delenv("AZURE_BATCH_MANAGE_POOLS", raising=False)

    cfg = Config().get_azure_batch_config()

    # explicit list is split + trimmed
    assert cfg["training_pool_ids"] == ["h100-pool", "t4-pool"]
    # unset lists fall back to the single legacy id
    assert cfg["inference_pool_ids"] == ["single-train"]
    assert cfg["imageryprep_pool_ids"] == ["single-prep"]
    # flags: SAS on (explicit), manage_pools default true
    assert cfg["use_sas"] is True
    assert cfg["manage_pools"] is True
