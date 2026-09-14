# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HASTELIB_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HASTELIB_ROOT))

from haste_artifacts import (  # noqa: E402
    RCBuild,
    artifact_set,
    image_record,
    read_json,
    registry_fingerprint,
    resolve_ci_build,
    validate_artifact_set,
    validate_wheel_manifest,
    wheel_manifest,
)

SOURCE_SHA = "a" * 40


def build(run_id: str = "12345") -> RCBuild:
    return RCBuild(
        SOURCE_SHA,
        run_id,
        "2026-09-11T10:00:00+00:00",
        1700000000,
        "1.0.43",
    )


def image(family: str, identity: RCBuild | None = None) -> dict:
    return image_record(
        identity or build(),
        family,
        "sha256:" + "c" * 64,
        registry_fingerprint("example.azurecr.io"),
    )


class FrozenBuildTests(unittest.TestCase):
    def test_parallel_runs_have_different_candidate_versions(self) -> None:
        self.assertEqual(build().version, "1.0.44rc12345")
        self.assertNotEqual(build().version, build("12346").version)

    def test_identity_round_trip_retains_exact_version(self) -> None:
        self.assertEqual(RCBuild.from_dict(build().to_dict()), build())

    def test_mutated_identity_is_rejected(self) -> None:
        for key, value in (
            ("source_sha", "not-a-sha"),
            ("build_run_id", True),
            ("source_date_epoch", True),
            ("schema_version", True),
            ("version", "99.0.0rc12345"),
            ("wheel_name", "../../foreign.whl"),
            ("repository", "another/repository"),
            ("build_created_at", "2026-09-11T10:00:00"),
        ):
            with self.subTest(field=key):
                altered = build().to_dict()
                altered[key] = value
                with self.assertRaises(ValueError):
                    RCBuild.from_dict(altered)

    def test_later_releases_do_not_change_an_existing_build(self) -> None:
        assets = [
            {
                "name": "hastegeo-1.0.43-py3-none-any.whl",
                "createdAt": "2026-09-10T10:00:00Z",
            },
            {
                "name": "hastegeo-1.0.44rc1-py3-none-any.whl",
                "createdAt": "2026-09-11T09:00:00Z",
            },
        ]
        run = {
            "id": 12345,
            "head_sha": SOURCE_SHA,
            "event": "pull_request",
            "repository": {"full_name": "microsoft/haste"},
            "path": ".github/workflows/hastegeo-build.yml",
            "created_at": "2026-09-11T10:00:00Z",
        }

        def runner(command):
            if command[0] == "git":
                return "1700000000"
            return json.dumps(
                run if command[1] == "api" else {"assets": assets}
            )

        first = resolve_ci_build(SOURCE_SHA, "12345", runner)
        assets.append(
            {
                "name": "hastegeo-2.0.0-py3-none-any.whl",
                "createdAt": "2026-09-11T10:00:01Z",
            }
        )
        assets.append(
            {
                "name": "hastegeo-1.1.0-py3-none-any.whl",
                "createdAt": "2026-09-11T10:00:00Z",
            }
        )
        self.assertEqual(resolve_ci_build(SOURCE_SHA, "12345", runner), first)
        self.assertEqual(first, build())

    def test_wrong_source_run_is_rejected_before_asset_lookup(self) -> None:
        calls = []

        def runner(command):
            calls.append(command)
            return json.dumps(
                {
                    "id": 12345,
                    "head_sha": "b" * 40,
                    "event": "pull_request",
                    "path": ".github/workflows/hastegeo-build.yml",
                    "repository": {"full_name": "microsoft/haste"},
                }
            )

        with self.assertRaisesRegex(ValueError, "source run"):
            resolve_ci_build(SOURCE_SHA, "12345", runner)
        self.assertEqual(len(calls), 1)

    def test_unavailable_release_history_is_not_a_silent_default(self) -> None:
        def unavailable(_command):
            raise ConnectionError("unavailable")

        with self.assertRaises(ConnectionError):
            resolve_ci_build(SOURCE_SHA, "12345", unavailable)


class ArtifactManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wheel = wheel_manifest(build(), "b" * 64)
        self.images = [image("training"), image("imageryprep")]

    def test_complete_artifact_set_matches_deployment_source(self) -> None:
        complete = artifact_set(self.wheel, self.images, build())
        self.assertEqual(
            validate_artifact_set(complete, build().version, SOURCE_SHA),
            build(),
        )
        self.assertNotIn("example.azurecr.io", json.dumps(complete))

    def test_wheel_bytes_and_identity_are_both_checked(self) -> None:
        with self.assertRaisesRegex(ValueError, "checksum"):
            validate_wheel_manifest(self.wheel, build(), "c" * 64)
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_wheel_manifest(self.wheel, build("12346"), "b" * 64)

    def test_missing_image_cannot_be_marked_ready(self) -> None:
        with self.assertRaisesRegex(ValueError, "both worker images"):
            artifact_set(self.wheel, self.images[:1], build())

    def test_duplicate_family_cannot_stand_in_for_missing_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            artifact_set(self.wheel, [self.images[0], self.images[0]], build())

    def test_mismatched_image_source_is_rejected(self) -> None:
        altered = copy.deepcopy(self.images)
        altered[0]["source_sha"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "provenance"):
            artifact_set(self.wheel, altered, build())

    def test_different_registries_cannot_be_combined(self) -> None:
        altered = copy.deepcopy(self.images)
        altered[0]["registry_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "same configured registry"):
            artifact_set(self.wheel, altered, build())

    def test_different_app_source_blocks_deployment(self) -> None:
        complete = artifact_set(self.wheel, self.images, build())
        with self.assertRaisesRegex(ValueError, "deployment source"):
            validate_artifact_set(complete, build().version, "d" * 40)

    def test_unknown_fields_and_oversized_documents_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(" " * 65537, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "size limit"):
                read_json(path)
        with self.assertRaisesRegex(ValueError, "fields"):
            RCBuild.from_dict({**build().to_dict(), "extra": True})


if __name__ == "__main__":
    unittest.main()
