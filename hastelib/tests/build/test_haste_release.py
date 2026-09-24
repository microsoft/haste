# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import subprocess
import sys
import unittest
from pathlib import Path

HASTELIB_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HASTELIB_ROOT))

from haste_release import (  # noqa: E402
    latest_stable,
    list_release_assets,
    next_dev,
    next_rc,
    parse_set_version,
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


class HasteReleaseDevChannelTests(unittest.TestCase):
    """The dev channel: an iteration aid that must never act like a release."""

    def test_resolve_dev_bumps_from_latest_stable(self):
        assets = ["hastegeo-1.0.25-py3-none-any.whl"]

        result = resolve(
            channel="dev", source_sha="abc", assets=assets, tags=[]
        )

        self.assertEqual("1.0.26.dev1", result.version)
        self.assertEqual(
            "hastegeo-1.0.26.dev1-py3-none-any.whl", result.wheel_name
        )

    def test_dev_never_mints_a_source_tag(self):
        result = resolve(
            channel="dev",
            source_sha="abc",
            assets=["hastegeo-1.0.25-py3-none-any.whl"],
            tags=["hastegeo-v1.0.25"],
        )

        self.assertEqual("", result.source_tag)

    def test_next_dev_increments_independently_of_rc(self):
        assets = [
            "hastegeo-1.0.25-py3-none-any.whl",
            "hastegeo-1.0.26rc7-py3-none-any.whl",
            "hastegeo-1.0.26.dev2-py3-none-any.whl",
        ]

        self.assertEqual(3, next_dev(assets, (1, 0, 26)))
        self.assertEqual(8, next_rc(assets, (1, 0, 26)))

    def test_dev_assets_do_not_shadow_the_stable_base(self):
        """A dev wheel must never be mistaken for the latest stable."""
        assets = [
            "hastegeo-1.0.25-py3-none-any.whl",
            "hastegeo-9.9.9.dev1-py3-none-any.whl",
        ]

        self.assertEqual((1, 0, 25), latest_stable(assets))

    def test_dev_orders_below_rc_and_stable(self):
        """PEP 440 ordering is what keeps a dev wheel out of release paths."""
        from packaging.version import Version

        self.assertLess(Version("1.0.26.dev1"), Version("1.0.26rc1"))
        self.assertLess(Version("1.0.26rc1"), Version("1.0.26"))

    def test_set_version_accepts_exact_dev_override(self):
        target, number = parse_set_version("1.0.26.dev4", "dev")

        self.assertEqual(((1, 0, 26), 4), (target, number))

    def test_set_version_rejects_dev_on_the_rc_channel(self):
        with self.assertRaises(ValueError):
            parse_set_version("1.0.26.dev4", "rc")

    def test_set_version_rejects_rc_on_the_dev_channel(self):
        with self.assertRaises(ValueError):
            parse_set_version("1.0.26rc4", "dev")

    def test_resolve_refuses_to_republish_an_existing_dev_asset(self):
        assets = [
            "hastegeo-1.0.25-py3-none-any.whl",
            "hastegeo-1.0.26.dev1-py3-none-any.whl",
        ]

        with self.assertRaises(ValueError):
            resolve(
                channel="dev",
                source_sha="abc",
                assets=assets,
                tags=[],
                set_version="1.0.26.dev1",
            )


class ExplicitZeroOverrideTests(unittest.TestCase):
    """rc0 and dev0 are valid PEP 440. `explicit or next_*()` discarded them,
    because 0 is falsy, and allocated a different number than was asked for."""

    ASSETS = [
        "hastegeo-1.0.25-py3-none-any.whl",
        "hastegeo-1.0.26rc5-py3-none-any.whl",
        "hastegeo-1.0.26.dev5-py3-none-any.whl",
    ]

    def test_exact_rc_zero_is_preserved(self):
        result = resolve(
            channel="rc",
            source_sha="abc",
            assets=self.ASSETS,
            tags=[],
            set_version="1.0.26rc0",
        )

        self.assertEqual("1.0.26rc0", result.version)

    def test_exact_dev_zero_is_preserved(self):
        result = resolve(
            channel="dev",
            source_sha="abc",
            assets=self.ASSETS,
            tags=[],
            set_version="1.0.26.dev0",
        )

        self.assertEqual("1.0.26.dev0", result.version)

    def test_absent_override_still_allocates_the_next_number(self):
        self.assertEqual(
            "1.0.26.dev6",
            resolve(
                channel="dev", source_sha="abc", assets=self.ASSETS, tags=[]
            ).version,
        )
        self.assertEqual(
            "1.0.26rc6",
            resolve(
                channel="rc", source_sha="abc", assets=self.ASSETS, tags=[]
            ).version,
        )
