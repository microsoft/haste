import unittest
from unittest.mock import Mock

from hastegeo.core.config import Config
from hastegeo.core.processors.session import (
    SessionAccessError,
    SessionBootstrapProcessor,
    bind_swa_object_id,
    index_unique_aad_users,
)


class TestSessionBootstrapProcessor(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.active_status = self.config.get_user_statuses().ACTIVE.value
        self.metadata = Mock()
        self.processor_factory = Mock(return_value=self.metadata)
        self.registry = Mock()
        self.registry.list_infos.return_value = []
        self.registry_factory = Mock(return_value=self.registry)
        self.processor = SessionBootstrapProcessor(
            config=self.config,
            processor_factory=self.processor_factory,
            registry_factory=self.registry_factory,
        )
        self.principal = {
            "userId": "OBJECT-ID",
            "userDetails": "analyst@example.com",
            "userRoles": ["authenticated", "contributors", "administrators"],
        }

    def test_stable_active_session_reads_acl_without_writing(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "objectId": "object-id",
                "email": "analyst@example.com",
                "userRoles": ["authenticated", "contributors"],
                "settings": {"theme": "dark"},
                "status": self.active_status,
            }
        ]

        result = self.processor.load(self.principal)

        self.metadata.load.assert_called_once_with("acl")
        self.metadata.save.assert_not_called()
        self.assertEqual(result.user.identityId, "OBJECT-ID")
        self.assertEqual(result.user.settings, {"theme": "dark"})
        self.assertEqual(result.user.userRoles, ["contributors"])
        self.assertNotIn("administrators", result.user.userRoles)

    def test_bound_object_id_does_not_fall_back_to_reused_email(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "objectId": "different-object-id",
                "email": "analyst@example.com",
                "userRoles": ["contributors"],
                "status": self.active_status,
            }
        ]

        with self.assertRaises(SessionAccessError):
            self.processor.load(self.principal)

    def test_authenticated_system_role_does_not_grant_access(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "userRoles": ["authenticated"],
                "status": self.active_status,
            }
        ]

        with self.assertRaises(SessionAccessError):
            self.processor.load(self.principal)

    def test_legacy_email_match_is_case_insensitive(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "Analyst@Example.com",
                "userRoles": ["contributors"],
                "status": self.active_status,
            }
        ]

        result = self.processor.load(self.principal)

        self.assertEqual(result.user.userId, "Analyst@Example.com")
        self.assertEqual(result.user.userRoles, ["contributors"])

    def test_inactive_user_returns_blocked_session(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "userRoles": ["contributors"],
                "status": self.config.get_user_statuses().INACTIVE.value,
            }
        ]

        result = self.processor.load(self.principal)

        self.assertEqual(result.user.userRoles, [])
        self.assertEqual(
            result.user.status,
            self.config.get_user_statuses().INACTIVE.value,
        )
        self.assertFalse(result.publishing.publishingEnabled)
        self.metadata.save.assert_not_called()

    def test_deleted_user_returns_inactive_session(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "userRoles": ["contributors"],
                "status": self.active_status,
                "deleted": True,
            }
        ]

        result = self.processor.load(self.principal)

        self.assertEqual(result.user.userRoles, [])
        self.assertEqual(
            result.user.status,
            self.config.get_user_statuses().INACTIVE.value,
        )

    def test_unknown_user_is_denied(self) -> None:
        self.metadata.load.return_value = []

        with self.assertRaises(SessionAccessError):
            self.processor.load(self.principal)

    def test_legacy_user_without_status_returns_inactive_session(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "userRoles": ["contributors"],
            }
        ]
        principal = {
            "userDetails": "analyst@example.com",
            "userRoles": ["contributors"],
        }

        result = self.processor.load(principal)

        self.assertEqual(result.user.identityId, "analyst@example.com")
        self.assertEqual(
            result.user.status,
            self.config.get_user_statuses().INACTIVE.value,
        )
        self.assertEqual(result.user.userRoles, [])

    def test_role_mismatch_is_denied(self) -> None:
        self.metadata.load.return_value = [
            {
                "userId": "analyst@example.com",
                "userRoles": ["administrators"],
                "status": self.active_status,
            }
        ]
        principal = dict(self.principal, userRoles=["contributors"])

        with self.assertRaises(SessionAccessError):
            self.processor.load(principal)

    def test_missing_principal_identity_is_denied(self) -> None:
        with self.assertRaises(SessionAccessError):
            self.processor.load({"userRoles": ["contributors"]})

        self.processor_factory.assert_not_called()

    def test_development_mode_can_create_ephemeral_session(self) -> None:
        self.metadata.load.side_effect = FileNotFoundError
        processor = SessionBootstrapProcessor(
            config=self.config,
            processor_factory=self.processor_factory,
            registry_factory=self.registry_factory,
            development_mode=True,
        )
        principal = {
            "userId": "development@local",
            "userDetails": "development@local",
            "userRoles": ["authenticated", "administrators"],
        }

        result = processor.load(principal)

        self.assertEqual(result.user.userId, "development@local")
        self.assertEqual(result.user.userRoles, ["administrators"])
        self.metadata.save.assert_not_called()


class TestBindSwaObjectId(unittest.TestCase):
    def test_binds_legacy_record_once(self) -> None:
        user = {"userId": "analyst@example.com", "objectId": None}

        matched = bind_swa_object_id(user, {"objectId": "object-id"})

        self.assertTrue(matched)
        self.assertEqual(user["objectId"], "object-id")

    def test_accepts_matching_bound_identity(self) -> None:
        user = {"objectId": "OBJECT-ID"}

        self.assertTrue(bind_swa_object_id(user, {"objectId": "object-id"}))

    def test_rejects_conflicting_bound_identity(self) -> None:
        user = {"objectId": "old-object-id"}

        matched = bind_swa_object_id(user, {"objectId": "new-object-id"})

        self.assertFalse(matched)
        self.assertEqual(user["objectId"], "old-object-id")

    def test_rejects_management_record_without_object_id(self) -> None:
        user = {"userId": "analyst@example.com", "objectId": None}

        matched = bind_swa_object_id(user, {"objectId": None})

        self.assertFalse(matched)
        self.assertIsNone(user["objectId"])


class TestIndexUniqueAadUsers(unittest.TestCase):
    def test_indexes_one_aad_identity_case_insensitively(self) -> None:
        app_user = {
            "login": "Analyst@Example.com",
            "provider": "aad",
            "objectId": "object-id",
        }

        result = index_unique_aad_users([app_user])

        self.assertEqual(result, {"analyst@example.com": app_user})

    def test_ignores_non_aad_and_missing_object_ids(self) -> None:
        result = index_unique_aad_users(
            [
                {
                    "login": "analyst@example.com",
                    "provider": "github",
                    "objectId": "github-id",
                },
                {
                    "login": "other@example.com",
                    "provider": "aad",
                    "objectId": None,
                },
            ]
        )

        self.assertEqual(result, {})

    def test_rejects_duplicate_aad_logins(self) -> None:
        result = index_unique_aad_users(
            [
                {
                    "login": "analyst@example.com",
                    "provider": "aad",
                    "objectId": "first-id",
                },
                {
                    "login": "ANALYST@example.com",
                    "provider": "aad",
                    "objectId": "second-id",
                },
            ]
        )

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
