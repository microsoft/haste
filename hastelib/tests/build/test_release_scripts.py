# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPO_ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

import cleanup_rc_releases  # noqa: E402
import publish_hastegeo_wheel  # noqa: E402
import resolve_hastegeo_deploy  # noqa: E402
import set_hastegeo_source  # noqa: E402


def create_wheel(
    directory: Path,
    version: str,
    *,
    metadata_version: str | None = None,
) -> Path:
    wheel = directory / f"hastegeo-{version}-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: hastegeo\n"
        f"Version: {metadata_version or version}\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"hastegeo-{version}.dist-info/METADATA",
            metadata,
        )
    return wheel


class WheelPublisherTests(unittest.TestCase):
    def test_validate_wheel_accepts_matching_rc_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26rc1")

            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26rc1", "rc"
            )

        self.assertEqual("1.0.26rc1", identity.version)
        self.assertEqual(64, len(identity.sha256))

    def test_validate_wheel_rejects_metadata_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(
                Path(temp_dir),
                "1.0.26rc1",
                metadata_version="1.0.26rc2",
            )

            with self.assertRaisesRegex(ValueError, "METADATA version"):
                publish_hastegeo_wheel.validate_wheel(wheel, "1.0.26rc1", "rc")

    def test_validate_wheel_rejects_stable_version_on_rc_channel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26")

            with self.assertRaisesRegex(ValueError, "requires an rcN"):
                publish_hastegeo_wheel.validate_wheel(wheel, "1.0.26", "rc")

    @patch.object(
        publish_hastegeo_wheel,
        "list_release_assets",
        return_value=["hastegeo-1.0.26rc1-py3-none-any.whl"],
    )
    def test_publish_existing_rc_fails_without_clobber(self, _assets):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26rc1")
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26rc1", "rc"
            )

            with self.assertRaisesRegex(ValueError, "will not be overwritten"):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha="abc",
                )

    @patch.object(
        publish_hastegeo_wheel,
        "list_release_assets",
        return_value=["hastegeo-1.0.26-py3-none-any.whl"],
    )
    def test_publish_rc_fails_after_stable_release_exists(self, _assets):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26rc3")
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26rc3", "rc"
            )

            with self.assertRaisesRegex(ValueError, "stable asset"):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha="abc",
                )

    @patch.object(
        publish_hastegeo_wheel,
        "get_tag_sha",
        return_value="abc",
    )
    @patch.object(
        publish_hastegeo_wheel,
        "list_release_assets",
        return_value=["hastegeo-1.0.26-py3-none-any.whl"],
    )
    def test_publish_existing_stable_for_same_sha_is_noop(self, _assets, _tag):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26")
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26", "release"
            )

            url = publish_hastegeo_wheel.publish(
                identity,
                channel="release",
                source_sha="abc",
            )

        self.assertTrue(url.endswith(identity.filename))

    @patch.object(
        publish_hastegeo_wheel,
        "get_tag_sha",
        return_value="different-sha",
    )
    def test_ensure_stable_tag_rejects_mismatched_source(self, _tag):
        with self.assertRaisesRegex(ValueError, "points to"):
            publish_hastegeo_wheel.ensure_stable_tag(
                "hastegeo-v1.0.26", "expected-sha"
            )

    @patch.object(publish_hastegeo_wheel, "run_command")
    @patch.object(publish_hastegeo_wheel, "ensure_stable_tag")
    @patch.object(
        publish_hastegeo_wheel,
        "list_release_assets",
        side_effect=[
            [],
            ["hastegeo-1.0.26-py3-none-any.whl"],
        ],
    )
    def test_publish_stable_creates_tag_then_uploads_without_clobber(
        self, _assets, ensure_tag, run_command
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26")
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26", "release"
            )

            publish_hastegeo_wheel.publish(
                identity,
                channel="release",
                source_sha="abc",
            )

        ensure_tag.assert_called_once_with("hastegeo-v1.0.26", "abc")
        upload_command = run_command.call_args.args[0]
        self.assertIn("upload", upload_command)
        self.assertNotIn("--clobber", upload_command)

    @patch.object(publish_hastegeo_wheel, "run_command")
    @patch.object(
        publish_hastegeo_wheel,
        "list_release_assets",
        side_effect=[[], []],
    )
    def test_publish_fails_if_uploaded_asset_is_not_visible(
        self, _assets, _run_command
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = create_wheel(Path(temp_dir), "1.0.26rc1")
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, "1.0.26rc1", "rc"
            )

            with self.assertRaisesRegex(RuntimeError, "asset is missing"):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha="abc",
                )


class DeployResolverTests(unittest.TestCase):
    def test_canonicalize_version_removes_rc_zero_padding(self):
        self.assertEqual(
            "1.5.0rc2",
            resolve_hastegeo_deploy.canonicalize_version("1.5.0.rc02"),
        )

    def test_resolve_deploy_wheel_rejects_missing_asset(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_hastegeo_deploy.resolve_deploy_wheel(
                "1.0.26",
                ["hastegeo-1.0.25-py3-none-any.whl"],
            )


class RequirementToggleTests(unittest.TestCase):
    def test_rewrite_is_idempotent_and_has_one_active_source(self):
        content = (
            "requests==2.33.0\n"
            "-e ../../hastelib\n"
            "# hastegeo @ https://example/old.whl\n"
            "hastegeo @ https://example/duplicate.whl\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            requirements = Path(temp_dir) / "requirements.txt"
            requirements.write_text(content, encoding="utf-8")

            set_hastegeo_source.rewrite(
                str(requirements),
                "wheel",
                "https://example/new.whl",
                "../../hastelib",
            )
            set_hastegeo_source.rewrite(
                str(requirements),
                "wheel",
                "https://example/new.whl",
                "../../hastelib",
            )
            lines = requirements.read_text(encoding="utf-8").splitlines()

        active = [
            line
            for line in lines
            if line.startswith("-e ") or line.startswith("hastegeo @ ")
        ]
        self.assertEqual(
            ["hastegeo @ https://example/new.whl"],
            active,
        )


class CleanupTests(unittest.TestCase):
    def test_plan_deletions_rejects_negative_keep(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            cleanup_rc_releases.plan_deletions([], -1, set())

    def test_load_retain_requires_configured_file(self):
        with self.assertRaises(FileNotFoundError):
            cleanup_rc_releases._load_retain("missing-retain-file.txt")

    def test_stable_release_removes_rc_except_retained_asset(self):
        assets = [
            {
                "name": "hastegeo-1.0.26-py3-none-any.whl",
                "apiUrl": "stable",
            },
            {
                "name": "hastegeo-1.0.26rc1-py3-none-any.whl",
                "apiUrl": "rc1",
            },
            {
                "name": "hastegeo-1.0.26rc2-py3-none-any.whl",
                "apiUrl": "rc2",
            },
        ]

        result = cleanup_rc_releases.plan_deletions(
            assets,
            keep=5,
            retain={"hastegeo-1.0.26rc2-py3-none-any.whl"},
        )

        self.assertEqual(
            ["hastegeo-1.0.26rc1-py3-none-any.whl"],
            [str(asset["name"]) for asset in result],
        )


if __name__ == "__main__":
    unittest.main()
