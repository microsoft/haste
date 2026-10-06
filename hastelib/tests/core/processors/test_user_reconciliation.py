import os
import unittest
from unittest.mock import Mock, patch

from hastegeo.core.config import Config
from hastegeo.core.processors.user_reconciliation import (
    _pending_check_times,
    reconcile_pending_user,
)
from hastegeo.core.utils.errors import MetadataConflictError


class VersionedMetadata:
    def __init__(self, users):
        self.users = [dict(user) for user in users]
        self.version = 1
        self.saves = []
        self.conflict_callback = None

    def load_with_version(self, key):
        return [dict(user) for user in self.users], self.version

    def load(self, key):
        return [dict(user) for user in self.users]

    def save_with_version(self, key, users, version):
        self.saves.append((users, version))
        if version != self.version:
            raise MetadataConflictError("stale ACL version")
        if self.conflict_callback:
            callback, self.conflict_callback = self.conflict_callback, None
            callback(self)
            raise MetadataConflictError("concurrent ACL write")
        self.users = [dict(user) for user in users]
        self.version += 1


class TestReconcilePendingUser(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(
            os.environ,
            {
                "STATIC_APP_SUBSCRIPTION_ID": "subscription-id",
                "STATIC_APP_RESOURCE_GROUP": "resource-group",
                "STATIC_APP_NAME": "static-site",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        _pending_check_times.clear()
        self.config = Config()
        self.pending = self.config.get_user_statuses().PENDING.value
        self.active = self.config.get_user_statuses().ACTIVE.value
        self.record = {
            "userId": "analyst@example.com",
            "email": "analyst@example.com",
            "objectId": None,
            "identityProvider": "aad",
            "userRoles": ["contributors"],
            "status": self.pending,
            "deleted": False,
            "settings": {"theme": "dark"},
        }
        self.principal_id = "aad-object-id"
        self.login = "analyst@example.com"
        self.swa_user = {
            "user_details": self.login,
            "provider": "aad",
            "roles": "contributors,authenticated,anonymous",
            "user_id": self.principal_id,
        }
        self.manager = Mock()
        self.manager.list_users.return_value = [self.swa_user]
        self.manager_factory = Mock(return_value=self.manager)

    def reconcile(self, metadata, **overrides):
        arguments = {
            "metadata": metadata,
            "current_users": [dict(self.record)],
            "target_user_id": self.login,
            "principal_id": self.principal_id,
            "login": self.login,
            "principal_provider": "aad",
            "initial_version": 1,
            "config": self.config,
            "user_manager_factory": self.manager_factory,
        }
        arguments.update(overrides)
        return reconcile_pending_user(**arguments)

    def test_exact_accepted_identity_and_roles_are_conditionally_activated(
        self,
    ) -> None:
        metadata = VersionedMetadata([self.record])

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.active)
        self.assertEqual(result[0]["objectId"], self.principal_id)
        self.assertEqual(result[0]["settings"], {"theme": "dark"})
        self.assertEqual(len(metadata.saves), 1)
        self.assertEqual(metadata.saves[0][1], 1)
        self.manager.list_users.assert_called_once()

    def test_active_or_deleted_records_do_not_query_swa_or_write(self) -> None:
        for record in (
            dict(self.record, status=self.active),
            dict(self.record, deleted=True),
        ):
            metadata = VersionedMetadata([record])
            result = self.reconcile(metadata, current_users=[record])
            self.assertEqual(result, [record])
            self.manager.list_users.assert_not_called()
            self.assertEqual(metadata.saves, [])

    def test_unaccepted_or_missing_swa_user_remains_pending(self) -> None:
        self.manager.list_users.return_value = []
        metadata = VersionedMetadata([self.record])

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

    def test_duplicate_swa_login_is_not_a_unique_identity_match(self) -> None:
        self.manager.list_users.return_value = [
            self.swa_user,
            dict(self.swa_user, user_id="different-object-id"),
        ]
        metadata = VersionedMetadata([self.record])

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

    def test_principal_object_id_must_match_swa_identity(self) -> None:
        metadata = VersionedMetadata([self.record])

        result = self.reconcile(metadata, principal_id="another-object-id")

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

    def test_bound_acl_object_id_must_match_swa_identity(self) -> None:
        record = dict(self.record, objectId="old-object-id")
        metadata = VersionedMetadata([record])

        result = self.reconcile(metadata, current_users=[record])

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(result[0]["objectId"], "old-object-id")
        self.assertEqual(metadata.saves, [])

    def test_role_mismatch_and_unexpected_roles_do_not_activate(self) -> None:
        for roles in ("administrators", "contributors,custom"):
            self.manager.list_users.return_value = [
                dict(self.swa_user, roles=roles)
            ]
            metadata = VersionedMetadata([self.record])
            result = self.reconcile(metadata)
            self.assertEqual(result[0]["status"], self.pending)
            self.assertEqual(metadata.saves, [])

    def test_non_aad_principal_or_acl_is_not_promoted(self) -> None:
        metadata = VersionedMetadata([self.record])
        result = self.reconcile(metadata, principal_provider="github")
        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

        record = dict(self.record, identityProvider="github")
        metadata = VersionedMetadata([record])
        result = self.reconcile(metadata, current_users=[record])
        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

    def test_management_lookup_failure_fails_closed(self) -> None:
        self.manager.list_users.side_effect = RuntimeError("not available")
        metadata = VersionedMetadata([self.record])

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(metadata.saves, [])

    def test_etag_conflict_rereads_and_preserves_concurrent_unrelated_change(
        self,
    ) -> None:
        metadata = VersionedMetadata([self.record])

        def concurrent_change(store):
            store.users.append(
                {"userId": "other@example.com", "status": "Active"}
            )
            store.version += 1

        metadata.conflict_callback = concurrent_change

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.active)
        self.assertEqual(result[0]["objectId"], self.principal_id)
        self.assertEqual(result[1]["userId"], "other@example.com")
        self.assertEqual(len(metadata.saves), 2)
        self.assertEqual(metadata.saves[1][1], 2)

    def test_etag_conflict_does_not_revive_concurrently_deactivated_user(
        self,
    ) -> None:
        metadata = VersionedMetadata([self.record])

        def concurrent_change(store):
            store.users[0]["status"] = (
                self.config.get_user_statuses().INACTIVE.value
            )
            store.users[0]["deleted"] = True
            store.version += 1

        metadata.conflict_callback = concurrent_change

        result = self.reconcile(metadata)

        self.assertEqual(
            result[0]["status"], self.config.get_user_statuses().INACTIVE.value
        )
        self.assertTrue(result[0]["deleted"])
        self.assertEqual(len(metadata.saves), 1)

    def test_concurrent_same_user_role_change_is_revalidated(self) -> None:
        metadata = VersionedMetadata([self.record])

        def concurrent_change(store):
            store.users[0]["userRoles"] = ["administrators"]
            store.version += 1

        metadata.conflict_callback = concurrent_change

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.pending)
        self.assertEqual(result[0]["userRoles"], ["administrators"])
        self.assertEqual(len(metadata.saves), 1)

    def test_recent_check_is_cooled_down(self) -> None:
        metadata = VersionedMetadata([self.record])
        identity_key = self.principal_id.casefold()
        _pending_check_times[identity_key] = __import__("time").monotonic()

        result = self.reconcile(metadata)

        self.assertEqual(result[0]["status"], self.pending)
        self.manager.list_users.assert_not_called()
        self.assertEqual(metadata.saves, [])


if __name__ == "__main__":
    unittest.main()
