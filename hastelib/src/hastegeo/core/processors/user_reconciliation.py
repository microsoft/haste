# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Narrow, on-demand reconciliation for returning pending SWA users."""
from collections.abc import Callable, Mapping
import logging
import threading
import time
from typing import Any

from ..config import Config
from ..models.users import User
from ..utils.data import filter_roles
from ..utils.errors import MetadataConflictError
from ..utils.metadata import MetadataUtils
from .user_acl import (
    metadata_allows_local_unconditional_writes,
    metadata_supports_conditional_writes,
)

_ALLOWED_ROLES = frozenset({"administrators", "contributors"})
_MAX_WRITE_ATTEMPTS = 3
_PENDING_CHECK_COOLDOWN_SECONDS = 10
_PENDING_CHECK_COOLDOWN_MAX_ENTRIES = 4096
_pending_check_lock = threading.Lock()
_pending_check_times: dict[str, float] = {}


def _field(record: Any, *names: str) -> Any:
    for name in names:
        if isinstance(record, Mapping):
            value = record.get(name)
        else:
            value = getattr(record, name, None)
        if value not in (None, ""):
            return value
    return None


def _as_role_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [role.strip() for role in value.split(",") if role.strip()]
    if isinstance(value, (list, tuple, set)):
        return [role for role in value if isinstance(role, str)]
    return []


def _swa_user_index(users: list[Any]) -> dict[str, Mapping[str, Any]]:
    users_by_login: dict[str, list[Mapping[str, Any]]] = {}
    for user in users:
        provider = str(_field(user, "provider") or "").strip().casefold()
        login = str(
            _field(
                user,
                "user_details",
                "userDetails",
                "display_name",
                "displayName",
            )
            or ""
        ).strip().casefold()
        object_id = str(
            _field(user, "user_id", "userId", "id") or ""
        ).strip()
        if provider == "aad" and login and object_id:
            users_by_login.setdefault(login, []).append(
                {
                    "login": login,
                    "provider": provider,
                    "roles": _field(user, "roles") or "",
                    "objectId": object_id,
                }
            )
    return {
        login: candidates[0]
        for login, candidates in users_by_login.items()
        if len(candidates) == 1
    }


def _load_acl_with_version(metadata: Any) -> tuple[list[dict], Any]:
    if metadata_supports_conditional_writes(metadata):
        return metadata.load_with_version("acl")
    return metadata.load("acl"), None


def _save_acl_with_version(
    metadata: Any, users: list[dict], version: Any
) -> None:
    if metadata_supports_conditional_writes(metadata):
        metadata.save_with_version("acl", users, version)
    else:
        if not metadata_allows_local_unconditional_writes(metadata):
            raise MetadataConflictError(
                "The ACL storage backend does not support conditional writes"
            )
        # Test doubles and local filesystem storage are non-concurrent
        # development paths.
        metadata.save("acl", users)


def _claim_pending_check(identity_key: str) -> bool:
    """Best-effort per-worker cooldown without writing ACL metadata."""
    now = time.monotonic()
    with _pending_check_lock:
        stale_before = now - 60
        for key, checked_at in list(_pending_check_times.items()):
            if checked_at < stale_before:
                del _pending_check_times[key]
        previous = _pending_check_times.get(identity_key)
        if (
            previous is not None
            and now - previous < _PENDING_CHECK_COOLDOWN_SECONDS
        ):
            return False
        if len(_pending_check_times) >= _PENDING_CHECK_COOLDOWN_MAX_ENTRIES:
            oldest_key = min(
                _pending_check_times, key=_pending_check_times.get
            )
            del _pending_check_times[oldest_key]
        _pending_check_times[identity_key] = now
        return True


def _pending_user_index(
    users: list[dict[str, Any]], target_user_id: str, login: str
) -> int | None:
    target_key = target_user_id.strip().casefold()
    login_key = login.strip().casefold()
    matches = []
    for index, user in enumerate(users):
        user_id = str(user.get("userId") or "").strip().casefold()
        email = str(user.get("email") or "").strip().casefold()
        if target_key and user_id == target_key:
            matches.append(index)
        elif login_key and login_key in {user_id, email}:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def _valid_swa_match(
    users: list[dict[str, Any]],
    index: int,
    swa_by_login: Mapping[str, Mapping[str, Any]],
    principal_id: str,
    login: str,
    principal_provider: str,
    config: Config,
) -> Mapping[str, Any] | None:
    user = users[index]
    login_key = login.strip().casefold()
    if not login_key or principal_provider not in ("", "aad"):
        return None

    acl_identifiers = {
        str(user.get("userId") or "").strip().casefold(),
        str(user.get("email") or "").strip().casefold(),
    }
    if login_key not in acl_identifiers:
        return None

    duplicate_acl_matches = [
        other_index
        for other_index, other in enumerate(users)
        if login_key
        in {
            str(other.get("userId") or "").strip().casefold(),
            str(other.get("email") or "").strip().casefold(),
        }
    ]
    if duplicate_acl_matches != [index]:
        return None

    identity_provider = str(
        user.get("identityProvider") or "aad"
    ).strip().casefold()
    swa_user = swa_by_login.get(login_key)
    if identity_provider != "aad" or swa_user is None:
        return None

    swa_object_id = str(swa_user.get("objectId") or "").strip()
    existing_object_id = str(user.get("objectId") or "").strip()
    principal_object_id = principal_id.strip()
    if (
        not swa_object_id
        or not principal_object_id
        or swa_object_id.casefold() != principal_object_id.casefold()
        or (
            existing_object_id
            and existing_object_id.casefold() != swa_object_id.casefold()
        )
    ):
        return None

    if any(
        other_index != index
        and str(other.get("objectId") or "").strip().casefold()
        == swa_object_id.casefold()
        for other_index, other in enumerate(users)
    ):
        return None

    expected_roles = set(filter_roles(user.get("userRoles")))
    swa_roles = set(filter_roles(_as_role_list(swa_user.get("roles"))))
    if (
        not expected_roles
        or expected_roles != swa_roles
        or not expected_roles.issubset(_ALLOWED_ROLES)
    ):
        return None

    return swa_user


def reconcile_pending_user(
    metadata: Any,
    current_users: list[dict[str, Any]],
    *,
    target_user_id: str,
    principal_id: str,
    login: str,
    principal_provider: str = "",
    initial_version: Any = None,
    config: Config | None = None,
    user_manager_factory: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Try to promote only the returning principal's eligible pending ACL row.

    The SWA management lookup is performed only for a non-deleted pending
    record. ACL changes use Blob ETags and revalidate against the newest ACL
    after a conflict; the caller receives a fresh ACL snapshot in every case.
    Lookup/write failures fail closed and leave the session pending.
    """
    config = config or Config()
    pending_status = config.get_user_statuses().PENDING.value
    active_status = config.get_user_statuses().ACTIVE.value
    identity_key = principal_id.strip().casefold() or login.strip().casefold()
    index = _pending_user_index(current_users, target_user_id, login)
    if index is None:
        return current_users
    target = current_users[index]
    if target.get("deleted", False) or target.get("status") != pending_status:
        return current_users
    invite = config.INVITE
    if not all(
        (
            invite.STATIC_APP_SUBSCRIPTION_ID,
            invite.STATIC_APP_RESOURCE_GROUP,
            invite.STATIC_APP_NAME,
        )
    ):
        return current_users
    if (
        not principal_id.strip()
        or not login.strip()
        or principal_provider.strip().casefold() not in ("", "aad")
        or str(target.get("identityProvider") or "aad").strip().casefold()
        != "aad"
        or not identity_key
        or not _claim_pending_check(identity_key)
    ):
        return current_users

    if user_manager_factory is None:
        from ..utils.user import UserManager

        user_manager_factory = UserManager
    try:
        swa_users = user_manager_factory(invite).list_users()
        swa_by_login = _swa_user_index(swa_users)
    except Exception as error:
        logging.getLogger(__name__).warning(
            "Pending SWA access check failed with %s", type(error).__name__
        )
        return current_users

    users_snapshot = current_users
    version: Any = None
    for attempt in range(_MAX_WRITE_ATTEMPTS):
        try:
            if attempt == 0:
                users = [dict(user) for user in users_snapshot]
                version = initial_version
            else:
                users, version = _load_acl_with_version(metadata)
                users = [dict(user) for user in users]
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Pending ACL re-read failed with %s", type(error).__name__
            )
            return users_snapshot

        index = _pending_user_index(users, target_user_id, login)
        if index is None:
            return users
        target = users[index]
        if (
            target.get("deleted", False)
            or target.get("status") != pending_status
        ):
            return users
        matched_swa_user = _valid_swa_match(
            users,
            index,
            swa_by_login,
            principal_id,
            login,
            principal_provider.strip().casefold(),
            config,
        )
        if matched_swa_user is None:
            return users

        target["objectId"] = matched_swa_user["objectId"]
        target["status"] = active_status
        target["updated_on"] = MetadataUtils.get_timestamp()
        try:
            _save_acl_with_version(metadata, users, version)
        except MetadataConflictError:
            if attempt + 1 < _MAX_WRITE_ATTEMPTS:
                continue
            logging.getLogger(__name__).warning(
                "Pending ACL promotion exhausted conditional write retries"
            )
            return _load_fresh_acl(metadata, users_snapshot)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Pending ACL promotion failed with %s", type(error).__name__
            )
            return _load_fresh_acl(metadata, users_snapshot)

        # Read back rather than assuming that the in-memory edit is still the
        # authoritative state immediately after the write. If verification
        # fails, retain the original pending snapshot and fail closed.
        return _load_fresh_acl(metadata, users_snapshot)

    return _load_fresh_acl(metadata, users_snapshot)


def _load_fresh_acl(metadata: Any, fallback: list[dict]) -> list[dict]:
    try:
        return metadata.load("acl")
    except Exception as error:
        logging.getLogger(__name__).warning(
            "Pending ACL verification read failed with %s",
            type(error).__name__,
        )
        return fallback
