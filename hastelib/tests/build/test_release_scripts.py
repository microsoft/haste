# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import shutil
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
import publish_hastegeo_artifacts  # noqa: E402
import publish_hastegeo_wheel  # noqa: E402
import resolve_hastegeo_deploy  # noqa: E402
import set_hastegeo_source  # noqa: E402
from haste_artifacts import (  # noqa: E402
    RCBuild,
    artifact_set,
    artifact_set_name,
    image_record,
    provenance_name,
    registry_fingerprint,
    wheel_manifest,
)


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
    def test_legacy_publication_is_explicit_and_retains_no_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = create_wheel(Path(directory), "1.0.26rc2")
            arguments = [
                "--wheel",
                str(wheel),
                "--expected-version",
                "1.0.26rc2",
                "--channel",
                "rc",
                "--source-sha",
                "a" * 40,
            ]
            with patch.object(publish_hastegeo_wheel, "publish") as publish:
                with self.assertRaisesRegex(
                    ValueError, "verified build provenance"
                ):
                    publish_hastegeo_wheel.main(arguments)
                publish.assert_not_called()
            with patch.object(
                publish_hastegeo_wheel, "publish", return_value=""
            ) as publish:
                self.assertEqual(
                    publish_hastegeo_wheel.main([*arguments, "--legacy-rc"]),
                    0,
                )
                publish.assert_called_once()
                self.assertIsNone(publish.call_args.kwargs["manifest"])
            with (
                patch.object(
                    publish_hastegeo_wheel,
                    "list_release_assets",
                    return_value=[wheel.name],
                ),
                self.assertRaisesRegex(ValueError, "will not be overwritten"),
            ):
                publish_hastegeo_wheel.main([*arguments, "--legacy-rc"])

    def test_legacy_switch_cannot_bypass_supplied_provenance(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot bypass"):
            publish_hastegeo_wheel.main(
                [
                    "--wheel",
                    "unused.whl",
                    "--expected-version",
                    "1.0.26rc2",
                    "--channel",
                    "rc",
                    "--source-sha",
                    "a" * 40,
                    "--legacy-rc",
                    "--build-identity",
                    "unused.json",
                ]
            )

    def test_retry_reuses_identical_rc_and_repairs_missing_provenance(self):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        with tempfile.TemporaryDirectory() as directory:
            wheel = create_wheel(Path(directory), build.version)
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, build.version, "rc"
            )
            manifest = wheel_manifest(build, identity.sha256)
            assets = [wheel.name]
            uploads = []

            def run(command):
                if "download" in command:
                    target = Path(command[command.index("--dir") + 1])
                    shutil.copyfile(wheel, target / wheel.name)
                elif "upload" in command:
                    name = Path(command[4]).name
                    assets.append(name)
                    uploads.append(name)
                return ""

            with (
                patch.object(
                    publish_hastegeo_wheel,
                    "list_release_assets",
                    side_effect=lambda: list(assets),
                ),
                patch.object(
                    publish_hastegeo_wheel, "run_command", side_effect=run
                ),
            ):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha=build.source_sha,
                    manifest=manifest,
                )
            self.assertEqual(uploads, [provenance_name(build)])

    def test_retry_rejects_different_wheel_bytes_without_uploading(self):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        with tempfile.TemporaryDirectory() as directory:
            wheel = create_wheel(Path(directory), build.version)
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, build.version, "rc"
            )

            def run(command):
                self.assertIn("download", command)
                target = Path(command[command.index("--dir") + 1])
                (target / wheel.name).write_bytes(b"different artifact")
                return ""

            with (
                patch.object(
                    publish_hastegeo_wheel,
                    "list_release_assets",
                    return_value=[wheel.name],
                ),
                patch.object(
                    publish_hastegeo_wheel, "run_command", side_effect=run
                ) as commands,
                self.assertRaisesRegex(ValueError, "checksum differs"),
            ):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha=build.source_sha,
                    manifest=wheel_manifest(build, identity.sha256),
                )
            self.assertEqual(commands.call_count, 1)

    def test_conflicting_provenance_is_checked_before_any_upload(self):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        with tempfile.TemporaryDirectory() as directory:
            wheel = create_wheel(Path(directory), build.version)
            identity = publish_hastegeo_wheel.validate_wheel(
                wheel, build.version, "rc"
            )
            with (
                patch.object(
                    publish_hastegeo_wheel,
                    "list_release_assets",
                    return_value=[provenance_name(build)],
                ),
                patch.object(
                    publish_hastegeo_wheel,
                    "verify_existing_json",
                    side_effect=ValueError("conflicting provenance"),
                ),
                patch.object(
                    publish_hastegeo_wheel, "run_command"
                ) as commands,
                self.assertRaisesRegex(ValueError, "conflicting"),
            ):
                publish_hastegeo_wheel.publish(
                    identity,
                    channel="rc",
                    source_sha=build.source_sha,
                    manifest=wheel_manifest(build, identity.sha256),
                )
            commands.assert_not_called()

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
    def test_rc_deploy_rejects_missing_complete_manifest(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            resolve_hastegeo_deploy.resolve_rc_artifact_set(
                "1.0.26rc12345",
                "a" * 40,
                ["hastegeo-1.0.26rc12345-py3-none-any.whl"],
            )

    def test_rc_deploy_rejects_a_different_application_sha(self):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        registry = registry_fingerprint("example.azurecr.io")
        manifest = artifact_set(
            wheel_manifest(build, "b" * 64),
            [
                image_record(build, family, "sha256:" + "c" * 64, registry)
                for family in ("training", "imageryprep")
            ],
            build,
        )

        def download(command):
            folder = Path(command[command.index("--dir") + 1])
            (folder / artifact_set_name(build.version)).write_text(
                json.dumps(manifest)
            )
            return ""

        with (
            patch.object(
                resolve_hastegeo_deploy, "run_command", side_effect=download
            ),
            self.assertRaisesRegex(ValueError, "deployment source"),
        ):
            resolve_hastegeo_deploy.resolve_rc_artifact_set(
                build.version, "d" * 40, [artifact_set_name(build.version)]
            )

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


class ImageProvenanceTests(unittest.TestCase):
    def test_complete_build_manifest_flows_through_validation_and_assembly(
        self,
    ):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity_path = root / "identity.json"
            identity_path.write_text(json.dumps(build.to_dict()))
            wheel = create_wheel(root, build.version)
            manifest_path = root / "build-manifest.json"
            common = [
                "--wheel",
                str(wheel),
                "--expected-version",
                build.version,
                "--channel",
                "rc",
                "--source-sha",
                build.source_sha,
                "--build-identity",
                str(identity_path),
            ]
            self.assertEqual(
                publish_hastegeo_wheel.main(
                    [
                        *common,
                        "--validate-only",
                        "--json-output",
                        str(manifest_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                publish_hastegeo_wheel.main(
                    [
                        *common,
                        "--validate-only",
                        "--manifest",
                        str(manifest_path),
                    ]
                ),
                0,
            )
            images = root / "images"
            images.mkdir()
            for family in ("training", "imageryprep"):
                record = image_record(
                    build,
                    family,
                    "sha256:" + "c" * 64,
                    registry_fingerprint("example.azurecr.io"),
                )
                (images / f"{family}.json").write_text(json.dumps(record))
            self.assertEqual(
                publish_hastegeo_artifacts.main(
                    [
                        "complete",
                        "--identity",
                        str(identity_path),
                        "--wheel-manifest",
                        str(manifest_path),
                        "--images",
                        str(images),
                        "--output-dir",
                        str(root / "complete"),
                    ]
                ),
                0,
            )
            complete = json.loads(
                (
                    root / "complete" / artifact_set_name(build.version)
                ).read_text()
            )
            self.assertEqual(complete["wheel"]["build"], build.to_dict())
            self.assertEqual(
                set(complete["images"]), {"training", "imageryprep"}
            )

    def test_image_must_match_source_labels_and_locked_metadata(self):
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        configuration = {
            "os": "linux",
            "architecture": "amd64",
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": build.source_sha,
                    "org.opencontainers.image.version": build.version,
                }
            },
        }
        metadata = {
            "digest": "sha256:" + "c" * 64,
            "changeableAttributes": {
                "writeEnabled": False,
                "deleteEnabled": False,
            },
        }
        record = publish_hastegeo_artifacts.record_image(
            build, "training", "example.azurecr.io", metadata, configuration
        )
        self.assertEqual(record["source_sha"], build.source_sha)
        self.assertNotIn("example.azurecr.io", json.dumps(record))
        for field in ("writeEnabled", "deleteEnabled"):
            for value in (True, None, "false", 0):
                with self.subTest(field=field, value=value):
                    metadata["changeableAttributes"] = {
                        "writeEnabled": False,
                        "deleteEnabled": False,
                        field: value,
                    }
                    with self.assertRaisesRegex(ValueError, "locked"):
                        publish_hastegeo_artifacts.record_image(
                            build,
                            "training",
                            "example.azurecr.io",
                            metadata,
                            configuration,
                        )
            with self.subTest(missing=field):
                metadata["changeableAttributes"] = {
                    name: False
                    for name in ("writeEnabled", "deleteEnabled")
                    if name != field
                }
                with self.assertRaisesRegex(ValueError, "locked"):
                    publish_hastegeo_artifacts.record_image(
                        build,
                        "training",
                        "example.azurecr.io",
                        metadata,
                        configuration,
                    )
        for attributes in (None, [], "locked"):
            with self.subTest(attributes=attributes):
                metadata["changeableAttributes"] = attributes
                with self.assertRaisesRegex(ValueError, "locked"):
                    publish_hastegeo_artifacts.record_image(
                        build,
                        "training",
                        "example.azurecr.io",
                        metadata,
                        configuration,
                    )
        configuration["config"]["Labels"][
            "org.opencontainers.image.revision"
        ] = ("b" * 40)
        with self.assertRaisesRegex(ValueError, "source build"):
            publish_hastegeo_artifacts.verify_image_configuration(
                build, configuration
            )


if __name__ == "__main__":
    unittest.main()
