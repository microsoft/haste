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
os.environ.setdefault("DATA_PATH", "/tmp/haste-session-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-session-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

from hastegeo.core.models.session import (  # noqa: E402
    SessionBootstrap,
    SessionPublishing,
    SessionUser,
)
from hastegeo.core.processors.session import SessionAccessError  # noqa: E402


def make_request(principal: dict | None = None) -> func.HttpRequest:
    headers = {}
    if principal is not None:
        headers["x-ms-client-principal"] = base64.b64encode(
            json.dumps(principal).encode("utf-8")
        ).decode("ascii")
    return func.HttpRequest(
        method="GET",
        url="http://localhost/api/GetSessionBootstrap",
        headers=headers,
        params={},
        route_params={},
        body=b"",
    )


def response_json(response: func.HttpResponse) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


class TestSessionBootstrapRoute(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.principal = {
            "userId": "object-id",
            "userDetails": "analyst@example.com",
            "userRoles": ["authenticated", "contributors"],
        }
        self.result = SessionBootstrap(
            user=SessionUser(
                userId="analyst@example.com",
                identityId="object-id",
                userRoles=["authenticated", "contributors"],
                settings={"theme": "dark"},
                status="Active",
            ),
            publishing=SessionPublishing(
                publishingEnabled=True,
                providers=[],
            ),
        )

    async def test_returns_resolved_session(self) -> None:
        processor = Mock()
        processor.load.return_value = self.result
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app,
            "SessionBootstrapProcessor",
            return_value=processor,
        ) as processor_type:
            response = await function_app.GetSessionBootstrap(
                make_request(self.principal)
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_json(response), self.result.model_dump())
        processor_type.assert_called_once_with(
            config=function_app.config,
            development_mode=False,
        )
        processor.load.assert_called_once_with(self.principal)

    async def test_missing_principal_is_unauthenticated(self) -> None:
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app, "SessionBootstrapProcessor"
        ) as processor_type:
            response = await function_app.GetSessionBootstrap(make_request())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response_json(response)["error"]["code"], "UNAUTHENTICATED"
        )
        processor_type.assert_not_called()

    async def test_unknown_user_is_forbidden(self) -> None:
        processor = Mock()
        processor.load.side_effect = SessionAccessError(
            "An active HASTE user is required."
        )
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app,
            "SessionBootstrapProcessor",
            return_value=processor,
        ):
            response = await function_app.GetSessionBootstrap(
                make_request(self.principal)
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response_json(response)["error"]["code"], "FORBIDDEN")

    async def test_blocked_user_returns_roleless_status_response(self) -> None:
        processor = Mock()
        blocked = self.result.model_copy(deep=True)
        blocked.user.status = "Inactive"
        blocked.user.userRoles = []
        blocked.publishing.publishingEnabled = False
        processor.load.return_value = blocked
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app,
            "SessionBootstrapProcessor",
            return_value=processor,
        ):
            response = await function_app.GetSessionBootstrap(
                make_request(self.principal)
            )

        self.assertEqual(response.status_code, 200)
        payload = response_json(response)
        self.assertEqual(payload["user"]["status"], "Inactive")
        self.assertEqual(payload["user"]["userRoles"], [])
        self.assertFalse(payload["publishing"]["publishingEnabled"])

    async def test_development_mode_uses_local_principal(self) -> None:
        processor = Mock()
        processor.load.return_value = self.result
        with patch.object(
            function_app, "DEVELOPMENT_MODE", True
        ), patch.object(
            function_app,
            "SessionBootstrapProcessor",
            return_value=processor,
        ) as processor_type:
            response = await function_app.GetSessionBootstrap(make_request())

        self.assertEqual(response.status_code, 200)
        processor_type.assert_called_once_with(
            config=function_app.config,
            development_mode=True,
        )
        processor.load.assert_called_once_with(
            {
                "userId": "development@local",
                "userDetails": "development@local",
                "userRoles": ["authenticated", "administrators"],
            }
        )

    async def test_internal_error_returns_safe_message(self) -> None:
        processor = Mock()
        processor.load.side_effect = RuntimeError("sensitive detail")
        with patch.object(
            function_app, "DEVELOPMENT_MODE", False
        ), patch.object(
            function_app,
            "SessionBootstrapProcessor",
            return_value=processor,
        ):
            response = await function_app.GetSessionBootstrap(
                make_request(self.principal)
            )

        self.assertEqual(response.status_code, 500)
        payload = response_json(response)
        self.assertEqual(payload["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("sensitive detail", response.get_body().decode())


if __name__ == "__main__":
    unittest.main()
