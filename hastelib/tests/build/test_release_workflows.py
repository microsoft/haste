# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseWorkflowPolicyTests(unittest.TestCase):
    def test_external_actions_are_pinned_to_full_sha(self):
        workflows = [
            ".github/workflows/hastegeo-build.yml",
            ".github/workflows/hastegeo-publish.yml",
            ".github/workflows/deploy-apps.yml",
            ".github/workflows/docker-build-and-push.yml",
            ".github/workflows/rc-cleanup.yml",
        ]

        failures = []
        for relative_path in workflows:
            path = REPO_ROOT / relative_path
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if "uses:" not in line:
                    continue
                reference = line.split("uses:", 1)[1].strip().split()[0]
                if reference.startswith("./"):
                    continue
                if not re.search(r"@[0-9a-f]{40}$", reference):
                    failures.append(
                        f"{relative_path}:{line_number}: {reference}"
                    )

        self.assertEqual([], failures)

    def test_action_shas_match_their_repositories(self):
        expected = {
            "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",  # pragma: allowlist secret
            "azure/login": "1384c340ab2dda50fed2bee3041d1d87018aa5e8",  # pragma: allowlist secret
        }
        workflows = [
            ".github/workflows/hastegeo-build.yml",
            ".github/workflows/hastegeo-publish.yml",
            ".github/workflows/deploy-apps.yml",
            ".github/workflows/docker-build-and-push.yml",
        ]

        failures = []
        for relative_path in workflows:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            for action, sha in expected.items():
                for reference in re.findall(
                    rf"{re.escape(action)}@([0-9a-f]{{40}})", text
                ):
                    if reference != sha:
                        failures.append(
                            f"{relative_path}: {action}@{reference}"
                        )

        self.assertEqual([], failures)

    def test_pr_build_job_has_no_write_credentials(self):
        workflow = (
            REPO_ROOT / ".github/workflows/hastegeo-build.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("id-token: write", workflow)

    def test_privileged_publisher_is_default_branch_workflow_run(self):
        workflow = (
            REPO_ROOT / ".github/workflows/hastegeo-publish.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_run:", workflow)
        self.assertIn(
            "ref: ${{ github.event.repository.default_branch }}",
            workflow,
        )
        self.assertNotIn("pull_request:", workflow)
        self.assertIn(
            "github.event.workflow_run.head_repository.full_name",
            workflow,
        )
        self.assertIn("PR head changed after the wheel build", workflow)
        self.assertIn("PR #$PR_NUMBER is not open", workflow)

    def test_rc_and_stable_are_both_automatic_but_kill_switched(self):
        workflow = (
            REPO_ROOT / ".github/workflows/hastegeo-publish.yml"
        ).read_text(encoding="utf-8")
        publisher = (
            REPO_ROOT / ".github/scripts/publish_hastegeo_wheel.py"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        rc_block = workflow.split("  publish-rc:", 1)[1].split(
            "  publish-stable:", 1
        )[0]
        stable_block = workflow.split("  publish-stable:", 1)[1].split(
            "  build-rc-images:", 1
        )[0]
        self.assertNotIn("environment:", rc_block)
        self.assertIn("HASTEGEO_RC_PUBLISH_ENABLED", rc_block)
        # Merging to the default branch is the release approval, so stable
        # publication carries no protected environment.
        # HASTEGEO_PUBLISH_ENABLED stays as the kill switch.
        self.assertNotIn("environment:", stable_block)
        self.assertIn("HASTEGEO_PUBLISH_ENABLED", stable_block)
        self.assertNotIn("HASTEGEO_RELEASE_APPROVAL_CONFIGURED", stable_block)
        self.assertIn("contents: write", workflow)
        self.assertNotIn("--clobber", publisher)

    def test_pr_workflow_does_not_build_images_twice(self):
        workflow = (
            REPO_ROOT / ".github/workflows/hastegeo-build.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("validate-images:", workflow)
        self.assertNotIn("docker build", workflow)

    def test_rc_images_use_exact_matching_wheel_version(self):
        workflow = (
            REPO_ROOT / ".github/workflows/hastegeo-publish.yml"
        ).read_text(encoding="utf-8")
        image_block = workflow.split("  build-rc-images:", 1)[1].split(
            "  rc-artifact-summary:", 1
        )[0]

        self.assertIn(
            "Stamp RC version into image source",
            image_block,
        )
        self.assertIn('IMAGE_REF="${IMAGE_NAME}:${VERSION}"', image_block)
        self.assertNotIn("TAG_PREFIX", image_block)
        self.assertIn("Reusing already locked RC image", image_block)

    def test_scheduled_cleanup_is_report_only(self):
        workflow = (REPO_ROOT / ".github/workflows/rc-cleanup.yml").read_text(
            encoding="utf-8"
        )
        report_block = workflow.split("  report:", 1)[1].split("  delete:", 1)[
            0
        ]
        delete_block = workflow.split("  delete:", 1)[1]

        self.assertNotIn("--apply", report_block)
        self.assertIn("environment: hastegeo-release", delete_block)
        self.assertIn("--apply", delete_block)

    def test_function_publish_failure_is_not_swallowed(self):
        deploy_script = (
            REPO_ROOT / ".github/scripts/deploy_apps.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "Function deployment completed but health check failed",
            deploy_script,
        )
        self.assertIn("func azure functionapp publish", deploy_script)

    def test_existing_docker_workflow_skips_hastelib_changes(self):
        workflow = (
            REPO_ROOT / ".github/workflows/docker-build-and-push.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("'hastelib/**'", workflow)
        self.assertIn(
            'HASTELIB_CHANGED="${{ needs.detect-changes.outputs.hastelib }}"',
            workflow,
        )
        self.assertIn('"$HASTELIB_CHANGED" != "true"', workflow)
        self.assertIn("Build and Push Docker Image", workflow)

    def test_rc_deploy_defaults_all_artifacts_to_same_version(self):
        workflow = (REPO_ROOT / ".github/workflows/deploy-apps.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('TRAINING_TAG="${TRAINING_INPUT:-$VERSION}"', workflow)
        self.assertIn('IMAGEPREP_TAG="${IMAGEPREP_INPUT:-$VERSION}"', workflow)
        self.assertIn(
            "RC deployments require matching wheel and image tags",
            workflow,
        )

    def test_hastegeo_pin_hooks_are_service_scoped(self):
        """The hastegeo pin/unpin hooks must be per service, never root-level.

        azd fires root-level hooks around the matching *command*, so a root
        `prepackage` runs for `azd package` but is skipped by `azd deploy`'s
        internal packaging step. The package then ships the unresolvable
        `-e ../../hastelib` line and the Oryx build fails with "not a valid
        editable requirement". The two placements look identical in review and
        only diverge at deploy time, so pin the invariant here.
        """
        config = yaml.safe_load(
            (REPO_ROOT / "azure.yaml").read_text(encoding="utf-8")
        )

        root_hooks = config.get("hooks") or {}
        for hook in ("prepackage", "postpackage"):
            self.assertNotIn(
                hook,
                root_hooks,
                f"'{hook}' must not be a root hook — azd deploy skips it, "
                "shipping an unresolvable editable requirement.",
            )

        # titiler has no hastegeo dependency and deliberately has neither hook.
        for service in ("api", "queues"):
            hooks = config["services"][service].get("hooks") or {}
            self.assertIn(
                "prepackage", hooks, f"service '{service}' lost its pin hook"
            )
            self.assertIn(
                "postpackage",
                hooks,
                f"service '{service}' lost its unpin hook",
            )

            pin = hooks["prepackage"]
            unpin = hooks["postpackage"]
            self.assertIn("pin-hastegeo-wheel.ps1", pin["run"])
            self.assertIn("unpin-hastegeo-wheel.ps1", unpin["run"])

            # Service hooks run with the service directory as cwd, so the paths
            # must climb back to the repo root.
            self.assertTrue(
                pin["run"].startswith("../../"),
                f"'{service}' pin hook path must be service-relative",
            )
            self.assertTrue(
                unpin["run"].startswith("../../"),
                f"'{service}' unpin hook path must be service-relative",
            )

            # A failed pin must fail the deploy: shipping an unpinned package
            # "succeeds" and only breaks at runtime.
            self.assertFalse(
                pin.get("continueOnError", False),
                f"'{service}' pin hook must not continueOnError",
            )


if __name__ == "__main__":
    unittest.main()
