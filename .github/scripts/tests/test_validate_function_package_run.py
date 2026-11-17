# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = (
    Path(__file__).resolve().parents[1] / "validate_function_package_run.py"
)
SPEC = importlib.util.spec_from_file_location("package_run", SCRIPT)
package_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_run)


class TestFunctionPackageRun(unittest.TestCase):
    def setUp(self) -> None:
        self.args = {
            "repository": "microsoft/haste",
            "source_ref": "refs/heads/feat/keyless",
            "source_sha": "a" * 40,
            "environment": "dev1",
            "candidate_dev1": True,
        }
        self.run = {
            "status": "completed",
            "conclusion": "success",
            "path": package_run.WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "head_sha": "a" * 40,
            "head_branch": "feat/keyless",
            "repository": {"full_name": "microsoft/haste"},
            "head_repository": {"full_name": "microsoft/haste"},
        }

    def test_explicit_dev1_candidate_accepts_exact_dispatched_build(
        self,
    ) -> None:
        package_run.validate_run(self.run, **self.args)

    def test_main_accepts_only_main_push(self) -> None:
        self.args.update(source_ref="refs/heads/main", candidate_dev1=False)
        self.run.update(head_branch="main", event="push")
        for environment in ("dev1", "dev2", "prod"):
            self.args["environment"] = environment
            package_run.validate_run(self.run, **self.args)
        self.run["event"] = "workflow_dispatch"
        with self.assertRaises(ValueError):
            package_run.validate_run(self.run, **self.args)

    def test_candidates_cannot_target_other_environments_or_tags(self) -> None:
        for change in (
            {"environment": "dev2"},
            {"environment": "prod"},
            {"candidate_dev1": False},
            {"source_ref": "refs/tags/candidate"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                package_run.validate_run(self.run, **{**self.args, **change})

    def test_wrong_workflow_sha_ref_event_or_result_is_rejected(self) -> None:
        for change in (
            {"path": ".github/workflows/other.yml"},
            {"head_sha": "b" * 40},
            {"head_branch": "other"},
            {"event": "pull_request"},
            {"status": "in_progress"},
            {"conclusion": "failure"},
            {"head_repository": {"full_name": "fork/haste"}},
            {"repository": {"full_name": "fork/haste"}},
            {"head_repository": None},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                package_run.validate_run({**self.run, **change}, **self.args)

    def evidence(self) -> tuple[dict, dict]:
        return (
            {
                "jobs": [
                    {"name": "attest-dev1-candidate", "conclusion": "success"}
                ]
            },
            {
                "artifacts": [
                    {
                        "name": f"haste-function-packages-{'a' * 40}",
                        "expired": False,
                    }
                ]
            },
        )

    def test_expired_or_unsigned_artifacts_are_rejected(self) -> None:
        jobs, artifacts = self.evidence()
        for job_list, artifact_list in (
            ([], artifacts["artifacts"]),
            (
                [{"name": "attest-dev1-candidate", "conclusion": "skipped"}],
                artifacts["artifacts"],
            ),
            (jobs["jobs"], []),
            (jobs["jobs"], [{**artifacts["artifacts"][0], "expired": True}]),
        ):
            with self.subTest(jobs=job_list), self.assertRaises(ValueError):
                package_run.validate_build_evidence(
                    job_list, artifact_list, "a" * 40, True
                )

    def test_auto_selection_skips_unsigned_newer_run(self) -> None:
        jobs, artifacts = self.evidence()
        with patch.object(
            package_run,
            "_gh_json",
            side_effect=[
                [{"databaseId": 2}, {"databaseId": 1}],
                self.run,
                {"jobs": []},
                artifacts,
                self.run,
                jobs,
                artifacts,
            ],
        ):
            self.assertEqual(package_run.resolve_run(**self.args), "1")

    def test_explicit_run_id_cannot_bypass_attestation_gate(self) -> None:
        _, artifacts = self.evidence()
        with patch.object(
            package_run,
            "_gh_json",
            side_effect=[self.run, {"jobs": []}, artifacts],
        ), self.assertRaises(ValueError):
            package_run.resolve_run("123", **self.args)

    def test_invalid_run_id_rejects_before_github_access(self) -> None:
        with patch.object(package_run, "_gh_json") as github:
            with self.assertRaises(ValueError):
                package_run.resolve_run("../runs", **self.args)
        github.assert_not_called()


if __name__ == "__main__":
    unittest.main()
