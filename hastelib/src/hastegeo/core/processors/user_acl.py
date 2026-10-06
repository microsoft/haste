# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from collections.abc import Mapping
from typing import Any

from ..utils.errors import MetadataConflictError

_MAX_WRITE_ATTEMPTS = 5


def metadata_supports_conditional_writes(metadata: Any) -> bool:
    """Inspect the storage backend, not just MetadataProcessor's wrappers."""
    storage = getattr(metadata, "storage", None)
    backend = getattr(storage, "data_layer", None)
    subject = backend if backend is not None else metadata
    return callable(
        getattr(type(subject), "load_with_version", None)
    ) and callable(getattr(type(subject), "save_with_version", None))


def metadata_allows_local_unconditional_writes(metadata: Any) -> bool:
    """Allow fallback only for local storage and lightweight test doubles."""
    storage = getattr(metadata, "storage", None)
    backend = getattr(storage, "data_layer", None)
    return (
        backend is None
        or type(backend).__name__ == "LocalFileSystemDataLayer"
    )


def _user_key(record: Mapping[str, Any]) -> str:
    value = (
        record.get("userId")
        or record.get("email")
        or record.get("objectId")
    )
    key = str(value or "").strip().casefold()
    if not key:
        raise MetadataConflictError(
            "A user ACL record has no stable identity key"
        )
    return key


def _index_users(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed = {}
    for record in records:
        key = _user_key(record)
        if key in indexed:
            raise MetadataConflictError(
                "The user ACL contains duplicate identity keys"
            )
        indexed[key] = record
    return indexed


def _merge_acl_changes(
    baseline: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    latest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rebase this request's record changes onto a newer ACL snapshot."""
    base_by_key = _index_users(baseline)
    desired_by_key = _index_users(desired)
    latest_by_key = _index_users(latest)
    merged = [dict(record) for record in latest]
    changed_keys = [
        key
        for key in dict.fromkeys(
            [*_user_order(baseline), *_user_order(desired)]
        )
        if base_by_key.get(key) != desired_by_key.get(key)
    ]

    for key in changed_keys:
        base_record = base_by_key.get(key)
        desired_record = desired_by_key.get(key)
        latest_record = latest_by_key.get(key)

        if base_record is None:
            if latest_record is None:
                merged.append(dict(desired_record))
            elif latest_record != desired_record:
                raise MetadataConflictError(
                    "A different user ACL record was concurrently created"
                )
            continue

        if desired_record is None:
            if latest_record is None:
                continue
            if latest_record != base_record:
                raise MetadataConflictError(
                    "A user ACL record changed while it was being removed"
                )
            merged = [
                record
                for record in merged
                if _user_key(record) != key
            ]
            latest_by_key.pop(key, None)
            continue

        if latest_record == desired_record:
            continue
        if latest_record != base_record:
            raise MetadataConflictError(
                "A user ACL record changed concurrently; retry the operation"
            )
        for index, record in enumerate(merged):
            if _user_key(record) == key:
                merged[index] = dict(desired_record)
                break

    return merged


def _user_order(records: list[dict[str, Any]]) -> list[str]:
    return [_user_key(record) for record in records]


def save_acl_with_rebase(
    metadata: Any,
    baseline: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    *,
    max_attempts: int = _MAX_WRITE_ATTEMPTS,
) -> list[dict[str, Any]]:
    """Conditionally save ACL edits while preserving concurrent changes.

    Azure Blob ETags provide the compare-and-swap boundary. On a conflict, the
    operation is rebased onto the newest list; edits to the same user conflict
    rather than silently overwriting each other. Non-versioned test/local
    adapters retain the ordinary save behavior.
    """
    if not metadata_supports_conditional_writes(metadata):
        if not metadata_allows_local_unconditional_writes(metadata):
            raise MetadataConflictError(
                "The ACL storage backend does not support conditional writes"
            )
        metadata.save("acl", desired)
        return desired

    for attempt in range(max_attempts):
        try:
            latest, version = metadata.load_with_version("acl")
        except FileNotFoundError as error:
            if baseline:
                raise MetadataConflictError(
                    "The user ACL disappeared during an update"
                ) from error
            latest, version = [], None

        merged = _merge_acl_changes(baseline, desired, latest)
        if merged == latest:
            return latest

        try:
            metadata.save_with_version("acl", merged, version)
            return merged
        except MetadataConflictError:
            if attempt + 1 == max_attempts:
                raise

    raise MetadataConflictError(
        "The user ACL remained busy after repeated conditional writes"
    )
