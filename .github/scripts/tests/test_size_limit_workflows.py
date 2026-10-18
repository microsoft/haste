"""Exercise the operator script without credentials, network calls or waits."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github" / "scripts"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
KEYS = (
    "HASTE_MAX_UPLOAD_BYTES",
    "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES",
    "PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES",
)
STUBS = r'''
az() {
    printf '%s\n' "$*" >> "$CALL_LOG"
    if [ "${FORBID_AZ:-}" = true ]; then return 99; fi
    case "$*" in
        "functionapp config appsettings set"*)
            if [[ "$*" == *hastequeue* && "${FAIL_QUEUE_WRITE:-}" == true ]]; then
                return 9
            fi ;;
        "functionapp config appsettings list"*)
            case "$*" in
                *HASTE_MAX_UPLOAD_BYTES*) echo 5368709120 ;;
                *HASTE_MAX_IMAGERY_DOWNLOAD_BYTES*) echo 8589934592 ;;
                *PUBLISH_ASSESSMENT_MAX_TOTAL_BYTES*) echo 536870912 ;;
            esac ;;
        "functionapp keys list"*)
            if [ "${FAIL_KEYS:-}" = true ]; then return 1; fi
            if [ -n "${FLAKY_KEYS:-}" ]; then
                tries=$(cat "$KEY_ATTEMPTS" 2>/dev/null || echo 0)
                tries=$((tries + 1))
                echo "$tries" > "$KEY_ATTEMPTS"
                if [ "$tries" -le "$FLAKY_KEYS" ]; then return 1; fi
            fi
            echo test-only-key ;;
        "functionapp show"*) echo example.invalid ;;
    esac
    return 0
}
curl() { printf '%s' "$MOCK_RESPONSE"; }
sleep() { :; }
export -f az curl sleep
bash "$SCRIPT" "$@"
'''


@unittest.skipUnless(BASH, "Bash is required for shell integration tests")
class TestUpdateWorkflow(unittest.TestCase):
    def run_script(
        self,
        overrides: dict[str, str] | None = None,
        dry_run: bool = False,
        deploy: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], str, str]:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.log"
            summary = Path(directory) / "summary.md"
            environment = {
                **os.environ,
                **dict.fromkeys(KEYS, ""),
                "PYTHON": Path(sys.executable).as_posix(),
                "SCRIPT": (SCRIPTS / "update_size_limits.sh").as_posix(),
                "CALL_LOG": log.as_posix(),
                "KEY_ATTEMPTS": (Path(directory) / "keys.count").as_posix(),
                "GITHUB_STEP_SUMMARY": summary.as_posix(),
                "GITHUB_ACTIONS": "false",
                "MOCK_RESPONSE": json.dumps({
                    "maxUploadBytes": 5368709120,
                    "maxImageryDownloadBytes": 8589934592,
                    "publishAssessmentMaxTotalBytes": 536870912,
                    "instanceId": "same-http-instance",
                }),
                **(overrides or {}),
            }
            arguments = ["dummy", "test", "abc", str(dry_run).lower()]
            if deploy:
                environment["SCRIPT"] = (
                    SCRIPTS / "deploy_apps.sh"
                ).as_posix()
                arguments = ["dummy"] * 14 + ["funcqueue"]
            result = subprocess.run(
                [BASH, "-c", STUBS, "test", *arguments],
                env=environment, capture_output=True, text=True,
                check=False, timeout=90,
            )
            return (
                result,
                log.read_text() if log.exists() else "",
                summary.read_text() if summary.exists() else "",
            )

    def test_dry_run_resolves_defaults_without_azure(self) -> None:
        result, calls, summary = self.run_script(
            {"FORBID_AZ": "true", KEYS[0]: "030GiB"}, dry_run=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, "")
        self.assertIn("HASTE_MAX_UPLOAD_BYTES=32212254720", result.stdout)
        self.assertIn("HASTE_MAX_IMAGERY_DOWNLOAD_BYTES=8589934592", result.stdout)
        self.assertIn("32212254720", summary)

    def test_invalid_input_prevents_all_azure_calls(self) -> None:
        for deploy in (False, True):
            with self.subTest(deploy=deploy):
                result, calls, _ = self.run_script(
                    {KEYS[2]: "18446744073710600192"}, deploy=deploy
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, "")

    def test_apply_targets_only_consuming_apps(self) -> None:
        result, calls, summary = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = [
            line for line in calls.splitlines()
            if line.startswith("functionapp config appsettings set")
        ]
        self.assertEqual(len(writes), 2)
        self.assertIn("--name testhasteabcfunc", writes[0])
        self.assertIn(KEYS[0] + "=5368709120", writes[0])
        self.assertIn(KEYS[2] + "=536870912", writes[0])
        self.assertNotIn(KEYS[1], writes[0])
        self.assertIn("--name testhastequeueabcfunc", writes[1])
        self.assertIn(KEYS[1] + "=8589934592", writes[1])
        self.assertNotIn(KEYS[0], writes[1])
        self.assertIn("were NOT verified", result.stdout)
        self.assertIn("->", summary)

    def test_missing_key_fails_instead_of_skipping_verification(self) -> None:
        result, _, _ = self.run_script({"FAIL_KEYS": "true"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP verification could not run", result.stderr)

    def test_endpoint_is_resolved_before_the_restart(self) -> None:
        """The key store stops answering for a few seconds after a restart, so
        reading the host key afterwards returned empty and failed verification
        even though the settings had been written."""
        _, calls, _ = self.run_script()
        order = calls.splitlines()
        first_key = next(
            i for i, line in enumerate(order)
            if line.startswith("functionapp keys list")
        )
        first_restart = next(
            i for i, line in enumerate(order)
            if line.startswith("functionapp restart")
        )
        self.assertLess(first_key, first_restart)

    def test_transient_key_failure_is_retried(self) -> None:
        result, calls, _ = self.run_script({"FLAKY_KEYS": "2"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no host key for", result.stderr)
        self.assertGreaterEqual(
            len([
                line for line in calls.splitlines()
                if line.startswith("functionapp keys list")
            ]),
            3,
        )

    def test_stale_http_sample_fails(self) -> None:
        result, _, _ = self.run_script({"MOCK_RESPONSE": "{}"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not converge", result.stderr)

    def test_partial_write_failure_preserves_recovery_output(self) -> None:
        result, calls, summary = self.run_script({"FAIL_QUEUE_WRITE": "true"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--name testhasteabcfunc", calls)
        self.assertIn("5368709120", summary)
        self.assertNotIn("Done:", result.stdout)


class TestDeploymentContract(unittest.TestCase):
    def test_workflows_share_variables_and_concurrency_group(self) -> None:
        for filename in ("deploy-apps.yml", "update-size-limits.yml"):
            content = (ROOT / ".github" / "workflows" / filename).read_text()
            with self.subTest(workflow=filename):
                for key in KEYS:
                    self.assertIn("${{ vars." + key + " }}", content)
                self.assertIn("group: haste-settings-${{ inputs.environment }}", content)
                self.assertIn("cancel-in-progress: false", content)

    def test_compiled_template_keeps_default_bounds_and_app_ownership(self) -> None:
        template = json.loads((ROOT / "infra" / "main.json").read_text())
        expected = {
            "maxUploadBytes": 5368709120,
            "maxImageryDownloadBytes": 8589934592,
            "publishAssessmentMaxTotalBytes": 536870912,
        }
        for name, default in expected.items():
            parameter = template["parameters"][name]
            self.assertEqual(parameter["defaultValue"], default)
            self.assertEqual(parameter["minValue"], 1048576)
            self.assertEqual(parameter["maxValue"], 1099511627776)
        resources = template["resources"]
        if isinstance(resources, dict):
            resources = resources.values()
        functions = next(
            resource for resource in resources
            if resource["name"] == "functions"
        )["properties"]["template"]["resources"]
        for resource in functions:
            name = resource["name"]
            if name not in ("fn-api", "fn-queue", "fn-titiler"):
                continue
            settings = json.dumps(resource["properties"]["parameters"])
            for key in KEYS:
                owner = "fn-queue" if key == KEYS[1] else "fn-api"
                self.assertEqual(key in settings, name == owner, (name, key))


if __name__ == "__main__":
    unittest.main()