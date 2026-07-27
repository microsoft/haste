# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Fail-fast validation of the Azure Batch settings block.

``Config.get_azure_batch_config()`` falls back to ``<placeholder>`` strings
when an application setting is absent, so a missing setting is not detected
until Azure rejects it — surfacing as an opaque API error far from the cause
(e.g. ``InvalidPropertyValue`` on ``registryServer``). Validating before the
first Batch call lets the failure name the setting that is actually missing.
"""

import re

PLACEHOLDER_PATTERN = re.compile(r"<[^<>]+>")

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


class BatchJobPoolMismatchError(RuntimeError):
    """Raised when a reused Batch job is pinned to a different pool."""


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
