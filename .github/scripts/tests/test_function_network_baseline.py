"""Pin the inbound network baseline of the function apps in the compiled template."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
FUNCTION_APPS = ("fn-api", "fn-titiler", "fn-queue")


def _resources(template: dict) -> list[dict]:
    resources = template["resources"]
    return (
        list(resources.values()) if isinstance(resources, dict) else resources
    )


def _named(resources: list[dict], name: str) -> dict:
    return next(
        resource for resource in resources if resource.get("name") == name
    )


class TestFunctionNetworkBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = json.loads(
            (ROOT / "infra" / "main.json").read_text(encoding="utf-8")
        )
        cls.functions = _named(_resources(cls.main), "functions")
        modules = _resources(cls.functions["properties"]["template"])
        cls.apps = {name: _named(modules, name) for name in FUNCTION_APPS}

    def parameters(self, app: str) -> dict:
        return self.apps[app]["properties"]["parameters"]

    def site(self, app: str) -> dict:
        template = self.apps[app]["properties"]["template"]
        return next(
            resource
            for resource in _resources(template)
            if resource["type"] == "Microsoft.Web/sites"
        )

    def test_titiler_main_site_allows_only_the_apim_subnet(self) -> None:
        parameters = self.parameters("fn-titiler")
        self.assertIs(parameters["restrictMainSite"]["value"], True)
        self.assertEqual(
            parameters["allowedInboundSubnetIds"]["value"],
            ["[variables('apimSubnetId')]"],
        )
        subnet = self.functions["properties"]["template"]["variables"][
            "apimSubnetId"
        ]
        self.assertIn("parameters('apimSubnetName')", subnet)

    def test_titiler_allows_the_subnet_apim_egresses_from(self) -> None:
        apim = _named(_resources(self.main), "apim")
        apim_subnet = apim["properties"]["parameters"]["defaultSubnetName"]
        titiler_subnet = self.functions["properties"]["parameters"][
            "apimSubnetName"
        ]
        self.assertEqual(apim_subnet, titiler_subnet)

    def test_titiler_scm_site_denies_everything_by_default(self) -> None:
        self.assertIs(
            self.parameters("fn-titiler")["restrictScmSite"]["value"], True
        )
        config = self.site("fn-titiler")["properties"]["siteConfig"]
        self.assertEqual(config["scmIpSecurityRestrictions"], [])
        self.assertIs(config["scmIpSecurityRestrictionsUseMain"], False)
        self.assertEqual(
            config["scmIpSecurityRestrictionsDefaultAction"],
            "[if(parameters('restrictScmSite'), 'Deny', 'Allow')]",
        )
        self.assertEqual(
            config["ipSecurityRestrictionsDefaultAction"],
            "[if(parameters('restrictMainSite'), 'Deny', 'Allow')]",
        )

    def test_function_sites_require_https_and_tls_12(self) -> None:
        for app in FUNCTION_APPS:
            with self.subTest(app=app):
                site = self.site(app)["properties"]
                config = site["siteConfig"]
                self.assertIs(site["httpsOnly"], True)
                self.assertEqual(config["minTlsVersion"], "1.2")
                self.assertEqual(config["scmMinTlsVersion"], "1.2")
                self.assertEqual(config["ftpsState"], "Disabled")

    def test_api_and_queue_ingress_is_unchanged(self) -> None:
        for app in ("fn-api", "fn-queue"):
            with self.subTest(app=app):
                parameters = self.parameters(app)
                self.assertIs(parameters["restrictMainSite"]["value"], False)
                self.assertIs(parameters["restrictScmSite"]["value"], False)


if __name__ == "__main__":
    unittest.main()
