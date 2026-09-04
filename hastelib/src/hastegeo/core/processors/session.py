from collections.abc import Callable, Mapping
from typing import Any

from ..config import Config
from ..models.session import SessionBootstrap, SessionPublishing, SessionUser
from ..models.users import User
from ..publishing.registry import PublishingProviderRegistry
from .metadata import MetadataProcessor

APPLICATION_ROLES = frozenset({"administrators", "contributors"})


def application_roles(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {
        role.strip().lower()
        for role in value
        if isinstance(role, str) and role.strip().lower() in APPLICATION_ROLES
    }


def find_principal_user(
    raw_users: list[dict[str, Any]],
    principal_id: str,
    login: str,
) -> User | None:
    users = [User(**raw_user) for raw_user in raw_users]
    normalized_principal_id = principal_id.casefold()
    if normalized_principal_id:
        for user in users:
            if (
                user.objectId
                and user.objectId.casefold() == normalized_principal_id
            ):
                return user

    legacy_candidates = {
        value.casefold() for value in (principal_id, login) if value
    }
    for user in users:
        if user.objectId:
            continue
        identifiers = {
            value.casefold() for value in (user.userId, user.email) if value
        }
        if identifiers.intersection(legacy_candidates):
            return user
    return None


def effective_application_roles(
    principal_roles: Any,
    acl_roles: Any,
) -> set[str]:
    return application_roles(principal_roles).intersection(
        application_roles(acl_roles)
    )


def index_unique_aad_users(
    app_users: list[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    users_by_login: dict[str, list[Mapping[str, Any]]] = {}
    for app_user in app_users:
        provider = str(app_user.get("provider") or "").strip().casefold()
        login = str(app_user.get("login") or "").strip().casefold()
        object_id = str(app_user.get("objectId") or "").strip()
        if provider != "aad" or not login or not object_id:
            continue
        users_by_login.setdefault(login, []).append(app_user)
    return {
        login: candidates[0]
        for login, candidates in users_by_login.items()
        if len(candidates) == 1
    }


def bind_swa_object_id(
    user: dict[str, Any], app_user: Mapping[str, Any] | None
) -> bool:
    if app_user is None:
        return False
    object_id = str(app_user.get("objectId") or "").strip()
    if not object_id:
        return False
    existing = str(user.get("objectId") or "").strip()
    if existing and existing.casefold() != object_id.casefold():
        return False
    if not existing:
        user["objectId"] = object_id
    return True


class SessionAccessError(PermissionError):
    pass


class SessionBootstrapProcessor:
    def __init__(
        self,
        config: Config | None = None,
        processor_factory: Callable[..., MetadataProcessor] = (
            MetadataProcessor
        ),
        registry_factory: Callable[..., PublishingProviderRegistry] = (
            PublishingProviderRegistry
        ),
        development_mode: bool = False,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory
        self.registry_factory = registry_factory
        self.development_mode = development_mode

    def load(self, principal: Mapping[str, Any]) -> SessionBootstrap:
        principal_id = self._string(principal.get("userId"))
        login = self._string(principal.get("userDetails"))
        if not principal_id and not login:
            raise SessionAccessError("Authentication is required.")

        user = self._load_user(principal_id, login)
        active_status = self.config.get_user_statuses().ACTIVE.value
        if user.deleted or user.status != active_status:
            pending_status = self.config.get_user_statuses().PENDING.value
            inactive_status = self.config.get_user_statuses().INACTIVE.value
            return SessionBootstrap(
                user=SessionUser(
                    userId=user.email or user.userId or login,
                    identityId=(
                        principal_id or user.objectId or user.userId or login
                    ),
                    userRoles=[],
                    settings=user.settings or {},
                    status=(
                        pending_status
                        if not user.deleted and user.status == pending_status
                        else inactive_status
                    ),
                ),
                publishing=SessionPublishing(
                    publishingEnabled=False,
                    providers=[],
                ),
            )

        effective_roles = sorted(
            effective_application_roles(
                principal.get("userRoles"), user.userRoles
            )
        )
        if not effective_roles:
            raise SessionAccessError("No active HASTE role is assigned.")

        registry = self.registry_factory(config=self.config)
        return SessionBootstrap(
            user=SessionUser(
                userId=user.email or user.userId or login,
                identityId=principal_id
                or user.objectId
                or user.userId
                or login,
                userRoles=effective_roles,
                settings=user.settings or {},
                status=user.status,
            ),
            publishing=SessionPublishing(
                publishingEnabled=bool(
                    self.config.publishing_config["publishing_enabled"]
                ),
                providers=registry.list_infos(),
            ),
        )

    def _load_user(self, principal_id: str, login: str) -> User:
        try:
            raw_users = self.processor_factory(
                data_type=self.config.get_metadata_types().USERS.value,
                config=self.config,
            ).load("acl")
        except FileNotFoundError:
            raw_users = []

        user = find_principal_user(raw_users, principal_id, login)
        if user is not None:
            return user

        if self.development_mode:
            active_status = self.config.get_user_statuses().ACTIVE.value
            return User(
                userId=login or principal_id,
                objectId=principal_id or None,
                email=login or principal_id,
                userRoles=["administrators"],
                status=active_status,
                settings={},
            )
        raise SessionAccessError("An active HASTE user is required.")

    @staticmethod
    def _string(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""
