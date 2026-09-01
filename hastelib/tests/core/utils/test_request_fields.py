# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest

from hastegeo.core.utils.request_fields import (
    changed_server_managed_fields,
    server_managed_fields_message,
)


class TestServerManagedFields(unittest.TestCase):
    def test_create_rejects_supplied_protected_fields(self) -> None:
        result = changed_server_managed_fields(
            {"name": "Layer", "status": "Processed"},
            {"status", "progressPct"},
        )

        self.assertEqual(result, ["status"])

    def test_update_allows_unchanged_protected_fields(self) -> None:
        result = changed_server_managed_fields(
            {"name": "Renamed", "status": "Processed"},
            {"status"},
            existing={"name": "Original", "status": "Processed"},
        )

        self.assertEqual(result, [])

    def test_update_rejects_changed_and_new_protected_fields(self) -> None:
        result = changed_server_managed_fields(
            {"status": "Processed", "progressPct": 100},
            {"status", "progressPct"},
            existing={"status": "Queued"},
        )

        self.assertEqual(result, ["progressPct", "status"])

    def test_message_is_stable_and_sorted(self) -> None:
        self.assertEqual(
            server_managed_fields_message(["status", "gpkgUrl"]),
            "Server-managed fields cannot be supplied or changed: gpkgUrl, status",
        )


if __name__ == "__main__":
    unittest.main()
