import base64
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-user-security-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-user-security-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app


def principal_header(email: str, roles: list[str] | None = None) -> str:
    principal = {
        "userId": "attacker-object-id",
        "userDetails": email,
        "userRoles": roles or ["authenticated", "contributors"],
    }
    return base64.b64encode(json.dumps(principal).encode()).decode()


def make_request(
    user: dict,
    principal_roles: list[str] | None = None,
) -> func.HttpRequest:
    return func.HttpRequest(
        method="PUT",
        url="http://localhost/api/PutUser",
        headers={
            "x-ms-client-principal": principal_header(
                "attacker@example.com", principal_roles
            )
        },
        params={},
        route_params={},
        body=json.dumps({"user": user, "action": "update"}).encode(),
    )


def user_record(
    email: str = "attacker@example.com",
    status: str = "Active",
) -> dict:
    return {
        "userId": email,
        "email": email,
        "name": email,
        "userRoles": ["contributors"],
        "settings": {},
        "status": status,
        "deleted": False,
    }


class TestPutUserSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_mix_own_email_with_victim_id(self) -> None:
        metadata = Mock()
        metadata.load.return_value = [user_record()]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.PutUser(
                make_request(
                    {
                        **user_record(),
                        "userId": "victim@example.com",
                    }
                )
            )

        self.assertEqual(response.status_code, 403)
        metadata.load.assert_called_once_with("acl")
        metadata.save.assert_not_called()

    async def test_non_admin_cannot_create_through_update(self) -> None:
        metadata = Mock()
        metadata.load.return_value = [user_record("other@example.com")]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.PutUser(make_request(user_record()))

        self.assertEqual(response.status_code, 403)
        metadata.save.assert_not_called()

    async def test_non_admin_cannot_reactivate_self(self) -> None:
        metadata = Mock()
        metadata.load.return_value = [
            user_record(
                status=function_app.config.get_user_statuses().INACTIVE.value
            )
        ]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.PutUser(make_request(user_record()))

        self.assertEqual(response.status_code, 403)
        metadata.save.assert_not_called()

    async def test_active_non_admin_can_update_own_settings(self) -> None:
        metadata = Mock()
        metadata.load.return_value = [user_record()]
        request_user = user_record()
        request_user["settings"] = {"theme": "dark"}
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.PutUser(make_request(request_user))

        self.assertEqual(response.status_code, 200)
        saved_users = metadata.save.call_args.args[1]
        self.assertEqual(saved_users[0]["settings"], {"theme": "dark"})

    async def test_stale_principal_admin_role_does_not_bypass_acl(
        self,
    ) -> None:
        request = make_request(
            user_record("victim@example.com"),
            ["authenticated", "administrators"],
        )
        metadata = Mock()
        metadata.load.return_value = [user_record()]
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.PutUser(request)

        self.assertEqual(response.status_code, 403)
        metadata.save.assert_not_called()

    async def test_stale_admin_role_cannot_read_admin_settings(self) -> None:
        metadata = Mock()
        metadata.load.return_value = [user_record()]
        request = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GetAdminSettings",
            headers={
                "x-ms-client-principal": principal_header(
                    "attacker@example.com",
                    ["authenticated", "administrators"],
                )
            },
            params={},
            route_params={},
            body=b"",
        )
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.GetAdminSettings(request)

        self.assertEqual(response.status_code, 403)
        metadata.load.assert_called_once_with("acl")

    async def test_non_admin_cannot_read_another_user(self) -> None:
        caller = user_record()
        caller["objectId"] = "attacker-object-id"
        metadata = Mock()
        metadata.load.return_value = [
            caller,
            user_record("victim@example.com"),
        ]
        request = func.HttpRequest(
            method="GET",
            url=(
                "http://localhost/api/GetUserById" "?userId=victim@example.com"
            ),
            headers={
                "x-ms-client-principal": principal_header(
                    "attacker@example.com"
                )
            },
            params={"userId": "victim@example.com"},
            route_params={},
            body=b"",
        )

        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "MetadataProcessor", return_value=metadata
        ):
            response = await function_app.GetUserById(request)

        self.assertEqual(response.status_code, 403)
        metadata.load.assert_called_once_with("acl")


if __name__ == "__main__":
    unittest.main()
