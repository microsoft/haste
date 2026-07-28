# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Fail-fast validation of the Azure Batch settings block.

``Config.get_azure_batch_config()`` falls back to ``<placeholder>`` strings
when an application setting is absent, so a missing setting is not detected
until Azure rejects it — surfacing as an opaque API error far from the cause
(e.g. ``InvalidPropertyValue`` on ``registryServer``). Validating before the
first Batch call lets the failure name the setting that is actually missing.

This module also resolves the Batch *job* id, which has to account for
capacity-aware routing: a Batch job is permanently bound to one pool, but the
pool is chosen per task, so a single static job id cannot span pools.
"""

import re

PLACEHOLDER_PATTERN = re.compile(r"<[^<>]+>")

# Azure Batch job ids are limited to 64 characters.
MAX_JOB_ID_LENGTH = 64

# Settings the runner needs for any submission, mapped to the application
# setting that supplies each one.
ALWAYS_REQUIRED = {
    "account_name": "AZURE_BATCH_ACCOUNT_NAME",
    "batch_url": "AZURE_BATCH_URL",
    "output_container_url": "AZURE_BATCH_OUTPUT_CONTAINER_URL",
}

# Only read when the runner creates or resizes its own pool; environments on
# pre-created (IaC/autoscale) pools never touch these.
POOL_MANAGEMENT_REQUIRED = {
    "registry_server": "AZURE_BATCH_REGISTRY_SERVER",
    "registry_image": "AZURE_BATCH_REGISTRY_IMAGE",
    "user_assigned_identity_resource_id": (
        "AZURE_BATCH_REGISTRY_IDENTITY_RESOURCE_ID"
    ),
}


class BatchConfigurationError(RuntimeError):
    """Raised when a required Azure Batch application setting is missing."""


def has_placeholder(value):
    """True when ``value`` still contains an unresolved ``<...>`` default."""
    return isinstance(value, str) and bool(PLACEHOLDER_PATTERN.search(value))


def validate_batch_config(batch_config, manage_pools=None):
    """Raise ``BatchConfigurationError`` if a required setting is unresolved.

    Args:
        batch_config: The dict from ``Config.get_azure_batch_config()``.
        manage_pools: Whether the runner manages its own pool. Defaults to the
            ``manage_pools`` entry of ``batch_config``. When false, the
            pool-creation settings are not required.
    """
    if manage_pools is None:
        manage_pools = batch_config.get("manage_pools", True)

    required = dict(ALWAYS_REQUIRED)
    if manage_pools:
        required.update(POOL_MANAGEMENT_REQUIRED)

    unresolved = []
    for key, env_var in sorted(required.items(), key=lambda kv: kv[1]):
        value = batch_config.get(key)
        if not value or has_placeholder(value):
            unresolved.append(f"{env_var} (resolved to {value!r})")

    if unresolved:
        raise BatchConfigurationError(
            "Azure Batch is not configured. Missing or unresolved "
            "application settings: "
            + "; ".join(unresolved)
            + ". Set these on the Function App and restart it."
        )


def resolve_job_id(base_job_id, selected_pool, candidate_pool_ids=None):
    """Return the Batch job id to use for a task routed to ``selected_pool``.

    A Batch job is permanently bound to the pool it was created against, and
    can only be re-pointed while it has no active tasks. Capacity-aware routing
    picks the pool per task, so reusing one static job id across pools breaks as
    soon as two tasks are in flight on different pools. Scoping the job id to
    the selected pool gives one job per pool and removes the conflict.

    Environments that are not routing across multiple pools keep their existing
    job id, so their jobs are not renamed.

    Args:
        base_job_id: The configured job id (e.g. ``IMAGERYPREP_BATCH_JOB_ID``).
        selected_pool: The pool this task was routed to.
        candidate_pool_ids: The pools routing may choose between.
    """
    if not selected_pool:
        return base_job_id
    candidates = list(candidate_pool_ids or [])

    # The default convention is job id == pool id, so follow the selected pool
    # and keep names clean rather than doubling the pool id up.
    if base_job_id in candidates:
        return selected_pool[:MAX_JOB_ID_LENGTH]

    # A single candidate cannot spill over, so leave custom ids untouched.
    if len(candidates) <= 1:
        return base_job_id

    # Reserve room for the suffix: truncating the base instead of the pool
    # keeps ids for two different pools distinct.
    room = MAX_JOB_ID_LENGTH - len(selected_pool) - 1
    if room <= 0:
        return selected_pool[:MAX_JOB_ID_LENGTH]
    return f"{base_job_id[:room]}-{selected_pool}"
