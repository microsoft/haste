import unittest

from hastegeo.core.processors.user_acl import (
    _merge_acl_changes,
    metadata_allows_local_unconditional_writes,
    metadata_supports_conditional_writes,
    save_acl_with_rebase,
)
from hastegeo.core.utils.errors import MetadataConflictError


class TestConditionalWriteCapability(unittest.TestCase):
    def test_metadata_wrapper_uses_backend_capability(self) -> None:
        class VersionedBackend:
            def load_with_version(self, key):
                return [], "etag"

            def save_with_version(self, key, users, version):
                pass

        class MetadataWrapper:
            def __init__(self, backend):
                self.storage = type("Storage", (), {"data_layer": backend})()

            def load_with_version(self, key):
                return self.storage.data_layer.load_with_version(key)

            def save_with_version(self, key, users, version):
                self.storage.data_layer.save_with_version(key, users, version)

        self.assertTrue(
            metadata_supports_conditional_writes(
                MetadataWrapper(VersionedBackend())
            )
        )
        local_metadata = MetadataWrapper(object())
        self.assertFalse(metadata_supports_conditional_writes(local_metadata))
        self.assertFalse(
            metadata_allows_local_unconditional_writes(local_metadata)
        )
        self.assertTrue(metadata_allows_local_unconditional_writes(object()))


class TestMergeAclChanges(unittest.TestCase):
    def test_preserves_unrelated_concurrent_user(self) -> None:
        baseline = [{"userId": "alice", "settings": {"old": True}}]
        desired = [{"userId": "alice", "settings": {"new": True}}]
        latest = [
            {"userId": "alice", "settings": {"old": True}},
            {"userId": "bob", "status": "Active"},
        ]

        merged = _merge_acl_changes(baseline, desired, latest)

        self.assertEqual(
            merged,
            [
                {"userId": "alice", "settings": {"new": True}},
                {"userId": "bob", "status": "Active"},
            ],
        )

    def test_conflicts_on_concurrent_edit_to_same_user(self) -> None:
        baseline = [{"userId": "alice", "status": "PendingAcceptance"}]
        desired = [{"userId": "alice", "status": "Active"}]
        latest = [{"userId": "alice", "status": "Inactive"}]

        with self.assertRaises(MetadataConflictError):
            _merge_acl_changes(baseline, desired, latest)

    def test_rebases_new_user_without_losing_concurrent_user(self) -> None:
        baseline = [{"userId": "alice"}]
        desired = [
            {"userId": "alice"},
            {"userId": "bob", "status": "PendingAcceptance"},
        ]
        latest = [
            {"userId": "alice"},
            {"userId": "carol", "status": "Active"},
        ]

        merged = _merge_acl_changes(baseline, desired, latest)

        self.assertEqual(
            merged,
            [
                {"userId": "alice"},
                {"userId": "carol", "status": "Active"},
                {"userId": "bob", "status": "PendingAcceptance"},
            ],
        )

    def test_identical_concurrent_add_is_idempotent(self) -> None:
        record = {"userId": "bob", "status": "PendingAcceptance"}

        merged = _merge_acl_changes([], [record], [dict(record)])

        self.assertEqual(merged, [record])


class TestSaveAclWithRebase(unittest.TestCase):
    def test_remote_backend_without_cas_fails_closed(self) -> None:
        class NonVersionedBackend:
            def save(self, key, users):
                raise AssertionError("must not perform an unconditional save")

        class MetadataWrapper:
            storage = type(
                "Storage", (), {"data_layer": NonVersionedBackend()}
            )()

            def save(self, key, users):
                self.storage.data_layer.save(key, users)

        with self.assertRaises(MetadataConflictError):
            save_acl_with_rebase(
                MetadataWrapper(),
                [{"userId": "alice", "status": "PendingAcceptance"}],
                [{"userId": "alice", "status": "Active"}],
            )

    def test_retries_after_etag_conflict_and_rebases_latest_acl(self) -> None:
        class VersionedMetadata:
            def __init__(self) -> None:
                self.reads = 0
                self.writes = []

            def load_with_version(self, key: str):
                self.reads += 1
                records = [{"userId": "alice", "status": "PendingAcceptance"}]
                if self.reads > 1:
                    records.append({"userId": "carol", "status": "Active"})
                return records, f"etag-{self.reads}"

            def save_with_version(self, key, records, version) -> None:
                self.writes.append((records, version))
                if len(self.writes) == 1:
                    raise MetadataConflictError("Concurrent write")

        metadata = VersionedMetadata()
        baseline = [{"userId": "alice", "status": "PendingAcceptance"}]
        desired = [
            {"userId": "alice", "status": "Active"},
        ]

        result = save_acl_with_rebase(metadata, baseline, desired)

        self.assertEqual(metadata.reads, 2)
        self.assertEqual(metadata.writes[1][1], "etag-2")
        self.assertEqual(
            result,
            [
                {"userId": "alice", "status": "Active"},
                {"userId": "carol", "status": "Active"},
            ],
        )

    def test_missing_acl_during_update_is_not_recreated_partially(
        self,
    ) -> None:
        class MissingMetadata:
            def __init__(self) -> None:
                self.writes = 0

            def load_with_version(self, key: str):
                raise FileNotFoundError("ACL removed")

            def save_with_version(self, key, records, version) -> None:
                self.writes += 1

        metadata = MissingMetadata()
        baseline = [
            {"userId": "alice", "status": "Active"},
            {"userId": "bob", "status": "Active"},
        ]
        desired = [
            {"userId": "alice", "status": "Inactive"},
            baseline[1],
        ]

        with self.assertRaises(MetadataConflictError):
            save_acl_with_rebase(metadata, baseline, desired)
        self.assertEqual(metadata.writes, 0)

    def test_conflict_on_same_user_is_not_retried_as_overwrite(self) -> None:
        class VersionedMetadata:
            def load_with_version(self, key: str):
                return [{"userId": "alice", "status": "Inactive"}], "etag"

            def save_with_version(self, key, records, version) -> None:
                raise AssertionError("must not overwrite concurrent ACL edit")

        with self.assertRaises(MetadataConflictError):
            save_acl_with_rebase(
                VersionedMetadata(),
                [{"userId": "alice", "status": "PendingAcceptance"}],
                [{"userId": "alice", "status": "Active"}],
            )


if __name__ == "__main__":
    unittest.main()
