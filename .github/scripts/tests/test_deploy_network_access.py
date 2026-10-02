"""Keep deployments from widening a function app's inbound access."""

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
sys.path.insert(0, str(SCRIPTS))

import function_network_baseline as baseline  # noqa: E402

GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
SUBNET = (
    "/subscriptions/0000/resourceGroups/rg/providers/"
    "Microsoft.Network/virtualNetworks/vnet/subnets/default"
)
RUNNER_IP = "20.1.2.3"
STUBS = r"""
az() { "$PYTHON" "$FAKE_AZ" "$@"; }
func() {
    printf 'func %s | rules: %s\n' "$*" "$("$PYTHON" "$FAKE_AZ" __rules__)" \
        >> "$CALL_LOG"
    return "${FUNC_EXIT:-0}"
}
curl() { printf '%s' "$RUNNER_IP"; }
sleep() { :; }
export -f az func curl sleep
bash "$SCRIPT" "$@"
"""


def contained_config(**overrides: object) -> dict:
    config = {
        "ipSecurityRestrictions": [
            {
                "name": "AllowSubnet-1",
                "action": "Allow",
                "priority": 100,
                "vnetSubnetResourceId": SUBNET,
            },
            {
                "name": "Deny all",
                "action": "Deny",
                "ipAddress": "Any",
                "priority": 2147483647,
            },
        ],
        "ipSecurityRestrictionsDefaultAction": "Deny",
        "scmIpSecurityRestrictions": [],
        "scmIpSecurityRestrictionsDefaultAction": "Deny",
        "scmIpSecurityRestrictionsUseMain": False,
        "minTlsVersion": "1.2",
        "scmMinTlsVersion": "1.2",
        "ftpsState": "Disabled",
    }
    config.update(overrides)
    return config


class TestNetworkBaselineHelper(unittest.TestCase):
    def test_contained_app_has_no_violations(self) -> None:
        site = {"properties": {"httpsOnly": True}}
        self.assertEqual(
            baseline.violations(contained_config(), site, SUBNET), []
        )

    def test_subnet_match_ignores_case_and_trailing_slash(self) -> None:
        self.assertTrue(
            baseline.has_subnet_rule(contained_config(), SUBNET.upper() + "/")
        )

    def test_open_sites_and_foreign_rules_are_violations(self) -> None:
        config = contained_config(
            ipSecurityRestrictionsDefaultAction="Allow",
            scmIpSecurityRestrictionsUseMain=True,
            scmIpSecurityRestrictions=[
                {"name": "dev laptop", "action": "Allow", "priority": 5}
            ],
            minTlsVersion="1.0",
            ftpsState="FtpsOnly",
        )
        problems = baseline.violations(config, {"httpsOnly": False}, SUBNET)
        self.assertEqual(
            problems,
            [
                "the main site does not deny traffic by default",
                "the scm site inherits the main-site rules",
                "unexpected allow rule 'dev laptop' on the scm site",
                "HTTPS-only is not enabled",
                "minTlsVersion is below 1.2",
                "FTP/FTPS publishing is not disabled",
            ],
        )

    def test_missing_subnet_rule_is_a_violation(self) -> None:
        problems = baseline.violations(
            contained_config(), {"httpsOnly": True}, SUBNET + "-other"
        )
        self.assertIn("the main site does not allow the APIM subnet", problems)
        self.assertIn(
            "unexpected allow rule 'AllowSubnet-1' on the main site", problems
        )

    def test_tls_13_meets_the_minimum(self) -> None:
        config = contained_config(minTlsVersion="1.3", scmMinTlsVersion="1.3")
        self.assertEqual(
            baseline.violations(config, {"httpsOnly": True}, SUBNET), []
        )

    def test_unset_default_denies_only_when_the_site_has_rules(self) -> None:
        config = contained_config(
            ipSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictions=[
                {
                    "name": "Allow all",
                    "action": "Allow",
                    "ipAddress": "Any",
                    "priority": 2147483647,
                }
            ],
        )
        self.assertEqual(baseline.deny_sites(config), ["main"])

    def test_unset_default_with_own_rules_meets_the_baseline(self) -> None:
        config = contained_config(
            ipSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictions=[
                {
                    "name": "Block internet",
                    "action": "Deny",
                    "ipAddress": "0.0.0.0/0",
                    "priority": 500,
                },
                {
                    "name": "Deny all",
                    "action": "Deny",
                    "ipAddress": "Any",
                    "priority": 2147483647,
                },
            ],
        )
        site = {"properties": {"httpsOnly": True}}
        self.assertEqual(baseline.violations(config, site, SUBNET), [])

    def test_unset_default_without_own_rules_is_a_violation(self) -> None:
        config = contained_config(
            ipSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictionsDefaultAction=None,
            scmIpSecurityRestrictions=[
                {
                    "name": "Allow all",
                    "action": "Allow",
                    "ipAddress": "Any",
                    "priority": 2147483647,
                }
            ],
        )
        site = {"properties": {"httpsOnly": True}}
        self.assertEqual(
            baseline.violations(config, site, SUBNET),
            [
                "the scm site does not deny traffic by default",
                "unexpected allow rule 'Allow all' on the scm site",
            ],
        )

    def test_explicit_allow_default_never_needs_a_runner_rule(self) -> None:
        config = contained_config(
            ipSecurityRestrictionsDefaultAction="Allow",
            scmIpSecurityRestrictionsDefaultAction="Allow",
        )
        self.assertEqual(baseline.deny_sites(config), [])

    def test_only_global_ipv4_runner_addresses_are_accepted(self) -> None:
        self.assertTrue(baseline.is_public_ipv4(RUNNER_IP))
        for address in ("10.0.0.4", "203.0.113.9", "2001:db8::1", "", "x"):
            with self.subTest(address=address):
                self.assertFalse(baseline.is_public_ipv4(address))


@unittest.skipUnless(BASH, "Bash is required for shell integration tests")
class TestDeployNetworkAccess(unittest.TestCase):
    def run_deploy(
        self,
        rules: dict[str, list[dict]] | None = None,
        defaults: dict[str, str | None] | None = None,
        component: str = "titiler",
        apim_subnet: str = SUBNET,
        fail_removals: int = 0,
        **environment: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str], dict]:
        state = {
            "apimSubnet": apim_subnet,
            "httpsOnly": True,
            "useMain": False,
            "defaults": defaults or {"main": None, "scm": None},
            "rules": rules or {"main": [], "scm": []},
            "failRemovals": fail_removals,
        }
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps(state), encoding="utf-8")
            log = Path(directory) / "calls.log"
            result = subprocess.run(
                [BASH, "-c", STUBS, "test", *(["dummy"] * 14), component],
                env={
                    **os.environ,
                    "PYTHON": Path(sys.executable).as_posix(),
                    "SCRIPT": (SCRIPTS / "deploy_apps.sh").as_posix(),
                    "FAKE_AZ": (
                        Path(__file__).parent / "fake_az.py"
                    ).as_posix(),
                    "FAKE_AZ_STATE": state_file.as_posix(),
                    "CALL_LOG": log.as_posix(),
                    "RUNNER_IP": RUNNER_IP,
                    "GITHUB_RUN_ID": "77",
                    "GITHUB_RUN_ATTEMPT": "2",
                    # Git Bash on Windows would rewrite /subscriptions/...
                    # arguments into filesystem paths.
                    "MSYS_NO_PATHCONV": "1",
                    "MSYS2_ARG_CONV_EXCL": "*",
                    **environment,
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            calls = log.read_text(encoding="utf-8").splitlines()
            final = json.loads(state_file.read_text(encoding="utf-8"))
        return result, calls, final

    def publish_line(self, calls: list[str]) -> str:
        return next(call for call in calls if call.startswith("func "))

    @staticmethod
    def rule_names(state: dict) -> list[str]:
        return [
            rule["name"] for rules in state["rules"].values() for rule in rules
        ]

    def test_open_titiler_is_contained_before_it_is_published(self) -> None:
        result, calls, final = self.run_deploy()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final["defaults"], {"main": "Deny", "scm": "Deny"})
        self.assertFalse(final["useMain"])
        self.assertEqual(
            [rule["vnetSubnetResourceId"] for rule in final["rules"]["main"]],
            [SUBNET],
        )
        self.assertEqual(final["rules"]["scm"], [])
        restart = next(
            index
            for index, call in enumerate(calls)
            if call.startswith("functionapp restart")
        )
        set_defaults = next(
            index
            for index, call in enumerate(calls)
            if call.startswith("functionapp config access-restriction set")
        )
        self.assertLess(set_defaults, restart)

    def test_publish_runs_through_a_temporary_runner_rule(self) -> None:
        result, calls, final = self.run_deploy()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("main:haste-ci-77-2", self.publish_line(calls))
        self.assertIn("scm:haste-ci-77-2", self.publish_line(calls))
        runner_rules = [
            call
            for call in calls
            if "access-restriction add" in call and "haste-ci-77-2" in call
        ]
        self.assertEqual(len(runner_rules), 2)
        for call in runner_rules:
            self.assertIn(f"--ip-address {RUNNER_IP}/32", call)
        self.assertEqual(self.rule_names(final), ["AllowSubnet-1"])

    def test_failed_publish_still_removes_the_runner_rule(self) -> None:
        result, calls, final = self.run_deploy(FUNC_EXIT="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scm:haste-ci-77-2", self.publish_line(calls))
        self.assertEqual(self.rule_names(final), ["AllowSubnet-1"])

    def test_transient_cleanup_failure_is_retried(self) -> None:
        result, _, final = self.run_deploy(fail_removals=1)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("WARNING", result.stderr)
        self.assertEqual(self.rule_names(final), ["AllowSubnet-1"])

    def test_cleanup_failure_after_publish_is_retried_at_exit(self) -> None:
        # Six failures use up the three attempts right after publishing (two
        # rules each); the exit handler's first attempt then succeeds.
        result, calls, final = self.run_deploy(fail_removals=6)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("trying again when the deployment ends", result.stderr)
        self.assertNotIn("ERROR", result.stderr)
        tagged = next(
            index
            for index, call in enumerate(calls)
            if call.startswith("functionapp update")
        )
        last_removal = max(
            index
            for index, call in enumerate(calls)
            if "access-restriction remove" in call
        )
        self.assertLess(tagged, last_removal)
        self.assertEqual(self.rule_names(final), ["AllowSubnet-1"])

    def test_runner_rule_that_cannot_be_removed_fails_the_run(self) -> None:
        result, calls, final = self.run_deploy(fail_removals=99)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Could not remove the temporary deploy rules", result.stderr
        )
        self.assertTrue(
            any(call.startswith("functionapp update") for call in calls)
        )
        self.assertIn("haste-ci-77-2", self.rule_names(final))

    def test_rules_left_by_an_earlier_run_are_removed(self) -> None:
        stale = {
            "name": "haste-ci-12-1",
            "action": "Allow",
            "priority": 90,
            "ipAddress": "20.9.9.9/32",
        }
        result, calls, final = self.run_deploy(
            rules={"main": [dict(stale)], "scm": [dict(stale)]},
            defaults={"main": "Deny", "scm": "Deny"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("haste-ci-12-1", self.publish_line(calls))
        self.assertEqual(self.rule_names(final), ["AllowSubnet-1"])

    def test_foreign_allow_rule_stops_the_deploy_and_is_kept(self) -> None:
        foreign = {
            "name": "dev laptop",
            "action": "Allow",
            "priority": 5,
            "ipAddress": "20.8.8.8/32",
        }
        result, calls, final = self.run_deploy(
            rules={"main": [foreign], "scm": []}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected allow rule 'dev laptop'", result.stderr)
        self.assertFalse(any(call.startswith("func ") for call in calls))
        self.assertIn(foreign, final["rules"]["main"])

    def test_missing_apim_subnet_stops_the_deploy(self) -> None:
        result, calls, final = self.run_deploy(apim_subnet="")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no VNet integration subnet", result.stderr)
        self.assertFalse(any("access-restriction" in call for call in calls))
        self.assertFalse(any(call.startswith("func ") for call in calls))
        self.assertEqual(final["defaults"], {"main": None, "scm": None})

    def test_open_queue_app_gets_no_runner_rule(self) -> None:
        result, calls, final = self.run_deploy(component="funcqueue")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("access-restriction" in call for call in calls))
        self.assertTrue(any(call.startswith("func ") for call in calls))
        self.assertEqual(final["defaults"], {"main": None, "scm": None})


if __name__ == "__main__":
    unittest.main()
