# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from azure.core.exceptions import ClientAuthenticationError
from azure.storage.blob import AccessPolicy, ContainerClient
from azure.storage.blob._generated.models import SignedIdentifier
from hastegeo.core.artifact_storage.azure_blob_artifact_storage import (
    AzureBlobArtifactStorage,
)
from hastegeo.core.data_layer.azure_blob_storage_data_layer import (
    AzureBlobStorageDataLayer,
)

Storage = AzureBlobArtifactStorage | AzureBlobStorageDataLayer
BACKENDS = (AzureBlobArtifactStorage, AzureBlobStorageDataLayer)
POLICY_ID = "managed-read"


class TestBlobAccessPolicy(unittest.TestCase):
    def storage(
        self,
        backend: type[Storage],
        policies: list[SignedIdentifier],
        public_access: str | None = None,
    ) -> Storage:
        # Bypass constructors: no credentials, container creation or network.
        storage = object.__new__(backend)
        storage.container_read_policy = POLICY_ID
        storage.sas_expiration_days = 90
        storage.logger = MagicMock()
        storage.container_client = MagicMock(spec=ContainerClient)
        storage.container_client.get_container_access_policy.return_value = {
            "signed_identifiers": policies,
            "public_access": public_access,
        }
        return storage

    def unrelated_policy(self) -> SignedIdentifier:
        return SignedIdentifier(
            id="unrelated-policy",
            access_policy=AccessPolicy(
                permission="rl",
                start="2020-01-01T00:00:00Z",
                expiry="2099-01-01T00:00:00Z",
            ),
        )

    def assert_expiry_window(
        self,
        expiry: datetime,
        before: datetime,
        after: datetime,
        days: int = 90,
    ) -> None:
        self.assertGreaterEqual(expiry, before + timedelta(days=days))
        self.assertLessEqual(expiry, after + timedelta(days=days))

    def test_existing_unexpired_policy_does_not_write_acl(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=30)
        for backend in BACKENDS:
            for expiry in (
                future,
                future.isoformat().replace("+00:00", "Z"),
                future.replace(tzinfo=None),
                future.replace(tzinfo=None).isoformat(),
            ):
                with self.subTest(backend=backend.__name__, expiry=expiry):
                    policy = AccessPolicy(permission="r", expiry=expiry)
                    storage = self.storage(
                        backend,
                        [
                            SignedIdentifier(
                                id=POLICY_ID, access_policy=policy
                            ),
                            self.unrelated_policy(),
                        ],
                    )
                    storage._create_or_update_managed_access_policy()
                    client = storage.container_client
                    client.get_container_access_policy.assert_called_once_with()
                    client.set_container_access_policy.assert_not_called()

    def test_expired_policy_renews_only_expiry_and_preserves_other_acl(
        self,
    ) -> None:
        past = datetime.now(timezone.utc) - timedelta(days=1)
        for backend in BACKENDS:
            for expiry in (past, past.isoformat().replace("+00:00", "Z")):
                for public_access in (None, "blob", "container"):
                    with self.subTest(
                        backend=backend.__name__,
                        expiry=expiry,
                        public_access=public_access,
                    ):
                        unrelated = self.unrelated_policy()
                        start = "2020-01-01T00:00:00Z"
                        storage = self.storage(
                            backend,
                            [
                                SignedIdentifier(
                                    id=POLICY_ID,
                                    access_policy=AccessPolicy(
                                        permission="rl",
                                        start=start,
                                        expiry=expiry,
                                    ),
                                ),
                                unrelated,
                            ],
                            public_access,
                        )
                        before = datetime.now(timezone.utc)
                        storage._create_or_update_managed_access_policy()
                        after = datetime.now(timezone.utc)
                        write = (
                            storage.container_client.set_container_access_policy
                        )
                        write.assert_called_once()
                        written = write.call_args.kwargs["signed_identifiers"]
                        self.assertEqual(
                            set(written), {POLICY_ID, unrelated.id}
                        )
                        self.assertEqual(
                            written[unrelated.id], unrelated.access_policy
                        )
                        self.assertEqual(written[POLICY_ID].permission, "rl")
                        self.assertEqual(written[POLICY_ID].start, start)
                        self.assert_expiry_window(
                            written[POLICY_ID].expiry, before, after
                        )
                        self.assertEqual(
                            write.call_args.kwargs["public_access"],
                            public_access,
                        )

    def test_missing_policy_is_added_without_dropping_other_acl(self) -> None:
        for backend in BACKENDS:
            for public_access in (None, "blob", "container"):
                for has_other_policy in (False, True):
                    with self.subTest(
                        backend=backend.__name__,
                        public_access=public_access,
                        has_other_policy=has_other_policy,
                    ):
                        unrelated = self.unrelated_policy()
                        storage = self.storage(
                            backend,
                            [unrelated] if has_other_policy else [],
                            public_access,
                        )
                        before = datetime.now(timezone.utc)
                        storage._create_or_update_managed_access_policy()
                        after = datetime.now(timezone.utc)
                        write = (
                            storage.container_client.set_container_access_policy
                        )
                        write.assert_called_once()
                        written = write.call_args.kwargs["signed_identifiers"]
                        self.assertEqual(
                            set(written),
                            {POLICY_ID, unrelated.id}
                            if has_other_policy
                            else {POLICY_ID},
                        )
                        if has_other_policy:
                            self.assertEqual(
                                written[unrelated.id], unrelated.access_policy
                            )
                        self.assertEqual(
                            str(written[POLICY_ID].permission), "r"
                        )
                        self.assertIsNone(written[POLICY_ID].start)
                        self.assert_expiry_window(
                            written[POLICY_ID].expiry, before, after
                        )
                        self.assertEqual(
                            write.call_args.kwargs["public_access"],
                            public_access,
                        )

    def test_artifact_policy_uses_configured_expiration_days(self) -> None:
        storage = self.storage(AzureBlobArtifactStorage, [])
        storage.sas_expiration_days = 7
        before = datetime.now(timezone.utc)
        storage._create_or_update_managed_access_policy()
        after = datetime.now(timezone.utc)
        written = (
            storage.container_client.set_container_access_policy.call_args
        )
        self.assert_expiry_window(
            written.kwargs["signed_identifiers"][POLICY_ID].expiry,
            before,
            after,
            days=7,
        )

    def test_existing_policy_without_expiry_is_not_rewritten(self) -> None:
        for backend in BACKENDS:
            for policy in (AccessPolicy(permission="r"), None):
                with self.subTest(backend=backend.__name__, policy=policy):
                    storage = self.storage(
                        backend,
                        [
                            SignedIdentifier(
                                id=POLICY_ID,
                                access_policy=policy,
                            )
                        ],
                    )
                    storage._create_or_update_managed_access_policy()
                    storage.container_client.set_container_access_policy.assert_not_called()

    def test_invalid_expiry_propagates_without_replacing_policy(self) -> None:
        for backend in BACKENDS:
            with self.subTest(backend=backend.__name__):
                storage = self.storage(
                    backend,
                    [
                        SignedIdentifier(
                            id=POLICY_ID,
                            access_policy=AccessPolicy(
                                permission="r", expiry="invalid"
                            ),
                        )
                    ],
                )
                with self.assertRaises(ValueError):
                    storage._create_or_update_managed_access_policy()
                storage.container_client.set_container_access_policy.assert_not_called()

    def test_acl_read_authorization_failure_propagates(self) -> None:
        for backend in BACKENDS:
            with self.subTest(backend=backend.__name__):
                storage = self.storage(backend, [])
                error = ClientAuthenticationError("ACL read denied")
                client = storage.container_client
                client.get_container_access_policy.side_effect = error
                with self.assertRaises(ClientAuthenticationError) as raised:
                    storage._create_or_update_managed_access_policy()
                self.assertIs(raised.exception, error)
                client.set_container_access_policy.assert_not_called()

    def test_acl_write_authorization_failure_propagates(self) -> None:
        for backend in BACKENDS:
            with self.subTest(backend=backend.__name__):
                storage = self.storage(backend, [self.unrelated_policy()])
                error = ClientAuthenticationError("ACL write denied")
                client = storage.container_client
                client.set_container_access_policy.side_effect = error
                with self.assertRaises(ClientAuthenticationError) as raised:
                    storage._create_or_update_managed_access_policy()
                self.assertIs(raised.exception, error)
                client.set_container_access_policy.assert_called_once()
