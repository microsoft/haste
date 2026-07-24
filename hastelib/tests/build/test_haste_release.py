# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import subprocess
import sys
import unittest
from pathlib import Path

HASTELIB_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HASTELIB_ROOT))

from haste_release import (  # noqa: E402
    list_release_assets,
    next_rc,
    resolve,
)


class HasteReleaseResolutionTests(unittest.TestCase):
    def test_resolve_rc_ignores_rc_when_selecting_stable_base(self):
        assets = [
            "hastegeo-1.0.25-py3-none-any.whl",
            "hastegeo-9.0.0rc8-py3-none-any.whl",
        ]

        result = resolve(
            channel="rc",
            source_sha="abc",
            assets=assets,
            tags=[],
        )

        self.assertEqual("1.0.26rc1", result.version)

    def test_next_rc_increments_highest_matching_target(self):
        assets = [
            "hastegeo-1.0.26rc1-py3-none-any.whl",
            "hastegeo-1.0.26rc3-py3-none-any.whl",
            "hastegeo-2.0.0rc9-py3-none-any.whl",
        ]

        result = next_rc(assets, (1, 0, 26))

        self.assertEqual(4, result)

    def test_resolve_exact_rc_override_preserves_requested_number(self):
        result = resolve(
            channel="rc",
            source_sha="abc",
            assets=["hastegeo-1.0.25-py3-none-any.whl"],
            tags=[],
            set_version="2.0.0rc7",
        )

        self.assertEqual("2.0.0rc7", result.version)

    def test_resolve_stable_tag_and_asset_is_idempotent(self):
        result = resolve(
            channel="release",
            source_sha="abc",
            assets=["hastegeo-1.0.26-py3-none-any.whl"],
            tags=["hastegeo-v1.0.26"],
        )

        self.assertTrue(result.already_published)
        self.assertEqual("1.0.26", result.version)

    def test_resolve_stable_tag_without_asset_reuses_same_version(self):
        result = resolve(
            channel="release",
            source_sha="abc",
            assets=["hastegeo-1.0.25-py3-none-any.whl"],
            tags=["hastegeo-v1.0.26"],
        )

        self.assertFalse(result.already_published)
        self.assertEqual("1.0.26", result.version)

    def test_resolve_existing_asset_without_source_tag_fails(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            resolve(
                channel="release",
                source_sha="abc",
                assets=[
                    "hastegeo-1.0.25-py3-none-any.whl",
                    "hastegeo-1.0.26-py3-none-any.whl",
                ],
                tags=[],
                set_version="1.0.26",
            )

    def test_resolve_without_stable_asset_requires_explicit_version(self):
        with self.assertRaisesRegex(ValueError, "No stable"):
            resolve(
                channel="rc",
                source_sha="abc",
                assets=[],
                tags=[],
            )

    def test_release_query_failure_propagates(self):
        def failing_runner(_command):
            raise subprocess.CalledProcessError(1, "gh")

        with self.assertRaises(subprocess.CalledProcessError):
            list_release_assets(runner=failing_runner)


if __name__ == "__main__":
    unittest.main()
