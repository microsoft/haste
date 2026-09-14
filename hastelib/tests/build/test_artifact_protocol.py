# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import base64
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import haste_artifact_protocol as protocol  # noqa: E402
import resolve_hastegeo_version as resolver  # noqa: E402
from haste_artifacts import RCBuild  # noqa: E402
from haste_release import Resolution  # noqa: E402


def capabilities_content(value: object = None) -> str:
    if value is None:
        value = {
            "schema_version": 1,
            "protocols": ["legacy", "run-bound-v1"],
        }
    return base64.b64encode(json.dumps(value).encode()).decode()


def artifact_response(*names: str, expired: bool = False) -> str:
    return json.dumps(
        [{"artifacts": [{"name": name, "expired": expired} for name in names]}]
    )


class ArtifactProtocolTests(unittest.TestCase):
    def test_missing_default_branch_capability_preserves_legacy(self) -> None:
        missing = subprocess.CalledProcessError(
            1, ["gh"], stderr="gh: Not Found (HTTP 404)"
        )
        runner = Mock(side_effect=["main\n", missing])
        self.assertEqual(
            protocol.producer_protocol("12345", "1", runner), "legacy"
        )
        self.assertIn("ref=main", runner.call_args.args[0])

    def test_advertised_default_branch_enables_run_bound_protocol(
        self,
    ) -> None:
        runner = Mock(side_effect=["main\n", capabilities_content()])
        self.assertEqual(
            protocol.producer_protocol("12345", "1", runner),
            "run-bound-v1",
        )
        committed = json.loads(
            (REPO_ROOT / protocol.CAPABILITIES_PATH).read_text()
        )
        self.assertEqual(
            committed,
            json.loads(base64.b64decode(capabilities_content())),
        )

    def test_lookup_errors_never_silently_downgrade(self) -> None:
        for message in ("HTTP 403", "HTTP 500", "connection timeout"):
            with self.subTest(error=message):
                error = subprocess.CalledProcessError(
                    1, ["gh"], stderr=message
                )
                runner = Mock(side_effect=["main\n", error])
                with self.assertRaises(subprocess.CalledProcessError):
                    protocol.producer_protocol("12345", "1", runner)

    def test_unknown_or_malformed_capabilities_fail_closed(self) -> None:
        for value in (
            {},
            {"schema_version": True, "protocols": list(protocol.PROTOCOLS)},
            {"schema_version": 2, "protocols": list(protocol.PROTOCOLS)},
            {"schema_version": 1, "protocols": ["future"]},
        ):
            with self.subTest(capabilities=value):
                runner = Mock(
                    side_effect=["main\n", capabilities_content(value)]
                )
                with self.assertRaisesRegex(ValueError, "capabilities"):
                    protocol.producer_protocol("12345", "1", runner)

    def test_protocol_names_preserve_run_and_attempt_contracts(self) -> None:
        self.assertEqual(
            protocol.artifact_name("12345", "2", "legacy"),
            "hastegeo-wheel-12345",
        )
        self.assertEqual(
            protocol.artifact_name("12345", "2", "run-bound-v1"),
            "hastegeo-wheel-12345-2",
        )
        for run_id, attempt in (("0", "1"), ("12345", "0"), ("../x", "1")):
            with self.subTest(run_id=run_id, attempt=attempt):
                runner = Mock()
                with self.assertRaises(ValueError):
                    protocol.producer_protocol(run_id, attempt, runner)
                runner.assert_not_called()

    def test_upgraded_publisher_accepts_old_and_new_builds(self) -> None:
        for expected in protocol.PROTOCOLS:
            with self.subTest(protocol=expected):
                name = protocol.artifact_name("12345", "2", expected)
                runner = Mock(return_value=artifact_response(name))
                self.assertEqual(
                    protocol.published_protocol("12345", "2", runner),
                    expected,
                )

    def test_publication_rejects_missing_ambiguous_or_wrong_attempt(
        self,
    ) -> None:
        for names in (
            (),
            ("hastegeo-wheel-12345-1",),
            ("hastegeo-wheel-54321-2",),
            ("hastegeo-wheel-12345", "hastegeo-wheel-12345-2"),
            ("hastegeo-wheel-12345", "hastegeo-wheel-12345"),
        ):
            with self.subTest(names=names):
                runner = Mock(return_value=artifact_response(*names))
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    protocol.published_protocol("12345", "2", runner)

    def test_publication_rejects_expired_artifacts(self) -> None:
        runner = Mock(
            return_value=artifact_response(
                "hastegeo-wheel-12345-1", expired=True
            )
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            protocol.published_protocol("12345", "1", runner)

    def test_retry_does_not_change_protocol_when_publisher_upgrades(
        self,
    ) -> None:
        runner = Mock(
            side_effect=[
                "main\n",
                capabilities_content(),
                artifact_response("hastegeo-wheel-12345"),
            ]
        )
        self.assertEqual(
            protocol.producer_protocol("12345", "2", runner), "legacy"
        )

    def test_retry_cannot_downgrade_existing_run_bound_identity(self) -> None:
        runner = Mock(
            side_effect=[
                "main\n",
                subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404"),
                artifact_response("hastegeo-wheel-12345-1"),
            ]
        )
        with self.assertRaisesRegex(ValueError, "instead of downgrading"):
            protocol.producer_protocol("12345", "2", runner)

    def test_retry_rejects_mixed_protocol_history(self) -> None:
        runner = Mock(
            side_effect=[
                "main\n",
                capabilities_content(),
                artifact_response(
                    "hastegeo-wheel-12345", "hastegeo-wheel-12345-1"
                ),
            ]
        )
        with self.assertRaisesRegex(ValueError, "mixed artifact protocols"):
            protocol.producer_protocol("12345", "2", runner)

    def test_producer_and_publisher_agree_on_both_names_and_versions(
        self,
    ) -> None:
        build = RCBuild(
            "a" * 40,
            "12345",
            "2026-09-11T10:00:00+00:00",
            1700000000,
            "1.0.25",
        )
        for selected in protocol.PROTOCOLS:
            with (
                self.subTest(protocol=selected),
                patch.object(
                    resolver, "producer_protocol", return_value=selected
                ),
                patch.object(
                    resolver, "published_protocol", return_value=selected
                ),
                patch.object(resolver, "resolve_ci_build", return_value=build),
                patch.object(
                    resolver,
                    "list_release_assets",
                    return_value=[
                        "hastegeo-1.0.25-py3-none-any.whl",
                        "hastegeo-1.0.26rc1-py3-none-any.whl",
                    ],
                ),
                patch.object(
                    resolver, "run_command", return_value="1700000000"
                ),
                patch.object(resolver, "emit_outputs") as emit,
            ):
                for mode in ("auto", "produced"):
                    resolver.main(
                        [
                            "--channel",
                            "rc",
                            "--source-sha",
                            build.source_sha,
                            "--build-run-id",
                            "12345",
                            "--build-attempt",
                            "1",
                            "--artifact-protocol",
                            mode,
                        ]
                    )
                producer, publisher = emit.call_args_list
                self.assertEqual(producer, publisher)
                expected_version = (
                    "1.0.26rc2" if selected == "legacy" else build.version
                )
                self.assertEqual(producer.args[0].version, expected_version)
                self.assertEqual(
                    producer.kwargs["name"],
                    protocol.artifact_name("12345", "1", selected),
                )

    def test_already_published_stable_needs_no_workflow_artifact(self) -> None:
        resolution = Resolution(
            "1.0.25",
            "hastegeo-1.0.25-py3-none-any.whl",
            "release",
            "a" * 40,
            "hastegeo-v1.0.25",
            True,
        )
        with (
            patch.object(resolver, "published_protocol") as discover,
            patch.object(resolver, "list_release_assets", return_value=[]),
            patch.object(resolver, "tags_pointing_at", return_value=[]),
            patch.object(resolver, "resolve", return_value=resolution),
            patch.object(resolver, "run_command", return_value="1700000000"),
            patch.object(resolver, "emit_outputs") as emit,
        ):
            resolver.main(
                [
                    "--channel",
                    "release",
                    "--source-sha",
                    "a" * 40,
                    "--build-run-id",
                    "12345",
                    "--artifact-protocol",
                    "produced",
                ]
            )
        discover.assert_not_called()
        self.assertTrue(emit.call_args.args[0].already_published)
        self.assertEqual(emit.call_args.kwargs["name"], "")


if __name__ == "__main__":
    unittest.main()
