"""What reconcile-titiler-baseline.ps1 removes, and that azd runs it."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from titiler_baseline import (  # noqa: E402
    stale_operations,
    stale_role_assignments,
)

ROOT = Path(__file__).resolve().parents[3]
PRINCIPAL = "11111111-2222-3333-4444-555555555555"
SUB = "/subscriptions/0000/resourceGroups/rg/providers/Microsoft.Storage"
OWN = f"{SUB}/storageAccounts/envhastetilerdev1sa"
SHARED = f"{SUB}/storageAccounts/envhastedev1sa"


def _assignment(name: str, scope: str, principal: str = PRINCIPAL) -> dict:
    return {
        "id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}",
        "principalId": principal,
        "scope": scope,
    }


class TestStaleRoleAssignments(unittest.TestCase):
    def test_keeps_own_account_and_children(self) -> None:
        assignments = [
            _assignment("a", OWN),
            _assignment("b", OWN.upper() + "/"),
            _assignment("c", f"{OWN}/blobServices/default/containers/x"),
        ]
        self.assertEqual(
            stale_role_assignments(assignments, PRINCIPAL, OWN), []
        )

    def test_removes_everything_else_for_the_principal(self) -> None:
        stale = [
            _assignment("owner", SHARED),
            _assignment("rg", "/subscriptions/0000/resourceGroups/rg"),
            # Prefix of the own account name is a different account.
            _assignment("prefix", OWN + "2"),
        ]
        other = _assignment("someone-else", SHARED, principal="ffff")
        result = stale_role_assignments(
            [*stale, other, _assignment("own", OWN)], PRINCIPAL.upper(), OWN
        )
        self.assertEqual(result, [a["id"] for a in stale])

    def test_requires_inputs(self) -> None:
        with self.assertRaises(ValueError):
            stale_role_assignments([], PRINCIPAL, "")
        with self.assertRaises(ValueError):
            stale_role_assignments([], " ", OWN)


class TestStaleOperations(unittest.TestCase):
    def test_only_get_tiles_survives(self) -> None:
        operations = [{"name": "get-tiles"}, {"name": "app"}, {"name": "x"}]
        self.assertEqual(stale_operations(operations), ["app", "x"])

    def test_cli(self) -> None:
        script = ROOT / ".github" / "scripts" / "titiler_baseline.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "stale-roles",
                "--principal-id",
                PRINCIPAL,
                "--allowed-scope",
                OWN,
            ],
            input=json.dumps(
                [_assignment("owner", SHARED), _assignment("own", OWN)]
            ),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            result.stdout.split(), [_assignment("owner", SHARED)["id"]]
        )


class TestHookWiring(unittest.TestCase):
    def test_reconcile_runs_after_provision(self) -> None:
        azure_yaml = (ROOT / "azure.yaml").read_text(encoding="utf-8")
        hooks = azure_yaml.split("\nhooks:", 1)[1]
        self.assertIn("postprovision:", hooks)
        block = hooks.split("postprovision:", 1)[1].split("\n  postdeploy:")[0]
        self.assertIn("continueOnError: false", block)
        self.assertIn("run: ./deploy/reconcile-titiler-baseline.ps1", block)


if __name__ == "__main__":
    unittest.main()
