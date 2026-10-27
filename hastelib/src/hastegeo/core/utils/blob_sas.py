# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Create short-lived read tokens scoped to one blob."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from azure.storage.blob import BlobSasPermissions, generate_blob_sas

READ_TOKEN_MINUTES = 60
CLOCK_SKEW_MINUTES = 5
# A delegation key must outlive every token signed with it.
DELEGATION_KEY_MARGIN = timedelta(minutes=READ_TOKEN_MINUTES + 5)


def blob_read_sas(
    account_name: str,
    container_name: str,
    blob_name: str,
    account_key: str | None = None,
    user_delegation_key=None,
    minutes: int = READ_TOKEN_MINUTES,
) -> str:
    """Return a read-only SAS token scoped to exactly one blob."""
    if account_key is None and user_delegation_key is None:
        raise ValueError(
            "Cannot mint a read token without an account or delegation key."
        )
    if minutes <= 0:
        raise ValueError("minutes must be positive")

    now = datetime.now(timezone.utc)
    return generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        user_delegation_key=user_delegation_key,
        permission=BlobSasPermissions(read=True),
        start=now - timedelta(minutes=CLOCK_SKEW_MINUTES),
        expiry=now + timedelta(minutes=minutes),
    )
