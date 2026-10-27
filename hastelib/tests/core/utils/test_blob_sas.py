# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""A read token must be worth no more than the blob it points at."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs

from hastegeo.core.utils.blob import (
    clear_blob_client_caches,
    get_cached_user_delegation_key,
)
from hastegeo.core.utils.blob_sas import blob_read_sas

ACCOUNT = "examplestorage"
CONTAINER = "data"
BLOB = "partition/imagery.tif"
# Not a real credential: any base64 string lets signing run offline.
FAKE_KEY = "Zm9vYmFyYmF6cXV1eGZvb2JhcmJhenF1dXhmb29iYXJiYXpxdXV4Zm9vYmE="  # pragma: allowlist secret  # gitleaks:allow


def _token(**overrides):
    kwargs = {
        "account_name": ACCOUNT,
        "container_name": CONTAINER,
        "blob_name": BLOB,
        "account_key": FAKE_KEY,
    }
    kwargs.update(overrides)
    return parse_qs(blob_read_sas(**kwargs))


class TestBlobReadSas(unittest.TestCase):
    def test_token_is_read_only_and_scoped_to_one_blob(self):
        token = _token()
        self.assertEqual(token["sr"], ["b"])
        self.assertEqual(token["sp"], ["r"])

    def test_token_has_expiry_and_no_stored_policy(self):
        token = _token()
        self.assertIn("se", token)
        self.assertNotIn("si", token)
        self.assertLess(token["st"][0], token["se"][0])

    def test_signature_covers_the_blob_name(self):
        self.assertNotEqual(
            _token()["sig"], _token(blob_name="other/imagery.tif")["sig"]
        )

    def test_expiry_follows_requested_minutes(self):
        short = _token(minutes=5)["se"][0]
        long = _token(minutes=60)["se"][0]
        self.assertLess(short, long)

    def test_requires_a_signing_key(self):
        with self.assertRaises(ValueError):
            blob_read_sas(ACCOUNT, CONTAINER, BLOB)

    def test_rejects_non_positive_lifetime(self):
        with self.assertRaises(ValueError):
            _token(minutes=0)


class TestDelegationKeyLifetime(unittest.TestCase):
    def setUp(self):
        clear_blob_client_caches()
        self.addCleanup(clear_blob_client_caches)

    def test_key_without_enough_life_is_refreshed(self):
        client = MagicMock()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        get_cached_user_delegation_key(client, now=now)
        # 100 minutes later the cached 2h key has 20 minutes left: enough
        # for the default margin but not for a 65 minute token.
        later = now + timedelta(minutes=100)
        get_cached_user_delegation_key(client, now=later)
        self.assertEqual(client.get_user_delegation_key.call_count, 1)
        get_cached_user_delegation_key(
            client, now=later, min_remaining=timedelta(minutes=65)
        )
        self.assertEqual(client.get_user_delegation_key.call_count, 2)


if __name__ == "__main__":
    unittest.main()
