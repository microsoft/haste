"""TiTiler's APIM surface: one GET operation, request limits, no op sync."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


def _resources(template: dict) -> list:
    resources = template["resources"]
    return (
        list(resources.values()) if isinstance(resources, dict) else resources
    )


class TestTitilerApimContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        main = json.loads(
            (ROOT / "infra" / "main.json").read_text(encoding="utf-8")
        )
        apis = next(r for r in _resources(main) if r.get("name") == "apimApis")
        cls.template = apis["properties"]["template"]

    def test_titiler_api_declares_only_get_tiles(self) -> None:
        operations = [
            r
            for r in _resources(self.template)
            if r["type"] == "Microsoft.ApiManagement/service/apis/operations"
            and "functionTitilerName"
            in json.dumps(r.get("dependsOn", [])) + r["name"]
        ]
        self.assertEqual(len(operations), 1)
        properties = operations[0]["properties"]
        self.assertEqual(properties["method"], "GET")
        self.assertEqual(
            properties["urlTemplate"], "/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
        )

    def test_titiler_policy_limits_requests(self) -> None:
        policy = self.template["variables"]["titilerPolicy"]
        self.assertEqual(policy.count("<rate-limit-by-key "), 2)
        self.assertIn('code="413"', policy)
        self.assertIn('code="414"', policy)
        self.assertIn("X-Forwarded-For", policy)


class TestTitilerIngress(unittest.TestCase):
    def test_op_sync_skips_titiler(self) -> None:
        script = (ROOT / "deploy" / "sync-apim-operations.ps1").read_text(
            encoding="utf-8"
        )
        default = next(
            line for line in script.splitlines() if "$FunctionApps" in line
        )
        self.assertIn("FUNCTION_API_NAME", default)
        self.assertNotIn("FUNCTION_TITILER_NAME", default)

    def test_titiler_function_accepts_get_only(self) -> None:
        binding = json.loads(
            (
                ROOT / "api" / "titilerfuncapi" / "app" / "function.json"
            ).read_text(encoding="utf-8")
        )["bindings"][0]
        self.assertEqual(binding["methods"], ["get"])


if __name__ == "__main__":
    unittest.main()
