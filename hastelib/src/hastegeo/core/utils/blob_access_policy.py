# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Maintain one stored read policy without replacing unrelated container ACLs."""

from datetime import datetime, timedelta, timezone

from azure.storage.blob import (
    AccessPolicy,
    ContainerClient,
    ContainerSasPermissions,
)


def ensure_container_read_policy(
    container_client: ContainerClient,
    policy_id: str,
    *,
    expiration_days: int,
) -> None:
    properties = container_client.get_container_access_policy()
    # The getter returns SignedIdentifier objects; the setter takes a mapping.
    policies = {
        identifier.id: identifier.access_policy
        for identifier in properties["signed_identifiers"]
    }
    now = datetime.now(timezone.utc)
    expiration_date = now + timedelta(days=expiration_days)
    if policy_id in policies:
        policy = policies[policy_id]
        # Omitted expiry is valid: the associated SAS may supply it instead.
        if policy is None or policy.expiry is None:
            return
        expiry = policy.expiry
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry >= now:
            return
        policy.expiry = expiration_date
    else:
        policies[policy_id] = AccessPolicy(
            permission=ContainerSasPermissions(read=True),
            expiry=expiration_date,
        )
    container_client.set_container_access_policy(
        signed_identifiers=policies,
        public_access=properties["public_access"],
    )
