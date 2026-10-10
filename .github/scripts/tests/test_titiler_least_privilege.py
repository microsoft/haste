"""Pin TiTiler's identity and storage isolation in the compiled template."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


def _resources(template: dict) -> list[dict]:
    resources = template["resources"]
    return (
        list(resources.values()) if isinstance(resources, dict) else resources
    )


def _named(resources: list[dict], name: str) -> dict:
    return next(
        resource for resource in resources if resource.get("name") == name
    )


def _of_type(template: dict, resource_type: str) -> list[dict]:
    return [
        resource
        for resource in _resources(template)
        if resource["type"] == resource_type
    ]


class TestTitilerLeastPrivilege(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = json.loads(
            (ROOT / "infra" / "main.json").read_text(encoding="utf-8")
        )
        cls.functions = _named(_resources(cls.main), "functions")
        modules = _resources(cls.functions["properties"]["template"])
        cls.titiler = _named(modules, "fn-titiler")
        cls.others = [_named(modules, n) for n in ("fn-api", "fn-queue")]
        cls.app_template = cls.titiler["properties"]["template"]
        storage = _named(_resources(cls.main), "storage")
        cls.storage_template = storage["properties"]["template"]

    def parameters(self, module: dict) -> dict:
        return module["properties"]["parameters"]

    def test_titiler_uses_its_own_host_storage(self) -> None:
        self.assertEqual(
            self.parameters(self.titiler)["hostStorageAccountName"]["value"],
            "[parameters('titilerStorageAccountName')]",
        )
        main_wiring = self.functions["properties"]["parameters"]
        self.assertIn(
            "titilerStorageAccountName",
            main_wiring["titilerStorageAccountName"]["value"],
        )
        self.assertIn(
            "hastetiler",
            self.main["variables"]["titilerStorageAccountName"],
        )

    def test_titiler_drops_shared_identity_mount_and_delegator(self) -> None:
        parameters = self.parameters(self.titiler)
        self.assertIs(parameters["attachSharedIdentity"]["value"], False)
        self.assertIs(parameters["mountDataShare"]["value"], False)
        self.assertIs(parameters["grantBlobDelegator"]["value"], False)

    def test_api_and_queue_keep_their_defaults(self) -> None:
        for module in self.others:
            with self.subTest(app=module["name"]):
                parameters = self.parameters(module)
                for name in (
                    "hostStorageAccountName",
                    "attachSharedIdentity",
                    "mountDataShare",
                    "grantBlobDelegator",
                ):
                    self.assertNotIn(name, parameters)

    def test_role_grants_are_scoped_to_the_host_account(self) -> None:
        assignments = _of_type(
            self.app_template, "Microsoft.Authorization/roleAssignments"
        )
        self.assertTrue(assignments)
        for assignment in assignments:
            with self.subTest(assignment=assignment["name"]):
                self.assertIn("hostStorageAccountName", assignment["scope"])

    def test_identity_and_mount_follow_the_switches(self) -> None:
        site = _of_type(self.app_template, "Microsoft.Web/sites")[0]
        self.assertIn("attachSharedIdentity", json.dumps(site["identity"]))
        self.assertIn("'SystemAssigned'", json.dumps(site["identity"]))
        mount = next(
            r
            for r in _of_type(self.app_template, "Microsoft.Web/sites/config")
            if "azurestorageaccounts" in r["name"]
        )
        # Always deployed, so turning the mount off removes an old one.
        self.assertNotIn("condition", mount)
        self.assertIn("mountDataShare", json.dumps(mount["properties"]))

    def test_titiler_storage_is_identity_only_and_private(self) -> None:
        account = next(
            r
            for r in _of_type(
                self.storage_template, "Microsoft.Storage/storageAccounts"
            )
            if "titilerStorageAccountName" in r["name"]
        )
        properties = account["properties"]
        self.assertIs(properties["allowSharedKeyAccess"], False)
        self.assertIs(properties["allowBlobPublicAccess"], False)
        self.assertEqual(properties["networkAcls"]["defaultAction"], "Deny")
        rules = properties["networkAcls"]["virtualNetworkRules"]
        self.assertEqual(len(rules), 1)
        self.assertIn("functionsSubnetId", rules[0]["id"])

    def test_shared_identity_has_no_role_on_titiler_storage(self) -> None:
        for assignment in _of_type(
            self.storage_template, "Microsoft.Authorization/roleAssignments"
        ):
            with self.subTest(assignment=assignment["name"]):
                self.assertNotIn(
                    "titilerStorageAccountName", assignment["scope"]
                )


if __name__ == "__main__":
    unittest.main()
