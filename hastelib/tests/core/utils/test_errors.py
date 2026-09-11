# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for describe_exception."""

import unittest

from hastegeo.core.utils.errors import (
    describe_exception,
    exception_diagnostics,
)


class _Message:
    def __init__(self, value):
        self.value = value
        self.lang = "en-US"


class _BatchError:
    def __init__(self, code, message=None):
        self.code = code
        self.message = message
        self.additional_properties = {}


class _AzureStyleException(Exception):
    def __init__(self, error):
        super().__init__("Request encountered an exception.")
        self.error = error


class TestDescribeException(unittest.TestCase):
    def test_renders_batch_error_as_code_and_message(self):
        exc = _AzureStyleException(
            _BatchError(
                "NodeNotReady",
                _Message(
                    "Node is not able to perform the requested operations "
                    "in its current state"
                ),
            )
        )
        self.assertEqual(
            describe_exception(exc),
            "NodeNotReady: Node is not able to perform the requested "
            "operations in its current state",
        )

    def test_strips_the_request_id_and_time_trailer(self):
        exc = _AzureStyleException(
            _BatchError(
                "NodeNotReady",
                _Message(
                    "Node is not able to perform the requested operations "
                    "in its current state\n"
                    "RequestId:a61bf14a-dcf1-4a68-b0ab-dddb878b4951\n"
                    "Time:2026-08-12T20:19:59.1266709Z"
                ),
            )
        )
        described = describe_exception(exc)
        self.assertNotIn("RequestId", described)
        self.assertNotIn("Time:", described)
        self.assertTrue(described.startswith("NodeNotReady: Node is not able"))

    def test_never_leaks_the_error_model_repr(self):
        exc = _AzureStyleException(
            _BatchError("NodeNotReady", _Message("node is busy"))
        )
        described = describe_exception(exc)
        self.assertNotIn("additional_properties", described)
        self.assertNotIn("'lang'", described)

    def test_falls_back_to_the_code_when_there_is_no_message(self):
        exc = _AzureStyleException(_BatchError("PoolNotFound"))
        self.assertEqual(describe_exception(exc), "PoolNotFound")

    def test_falls_back_to_str_for_plain_exceptions(self):
        self.assertEqual(
            describe_exception(ValueError("bad imagery url")),
            "bad imagery url",
        )

    def test_never_returns_an_empty_string(self):
        self.assertEqual(describe_exception(RuntimeError()), "RuntimeError")

    def test_handles_a_plain_string_message(self):
        exc = _AzureStyleException(_BatchError("NodeNotFound", "node is gone"))
        self.assertEqual(describe_exception(exc), "NodeNotFound: node is gone")


class TestExceptionDiagnostics(unittest.TestCase):
    def test_cause_codes_and_locations_exclude_messages_and_source_lines(
        self,
    ) -> None:
        from azure.core.exceptions import HttpResponseError

        cause = HttpResponseError("https://storage/blob?sig=private-token")
        cause.status_code = 403
        cause.error_code = "AuthorizationPermissionMismatch"
        try:
            try:
                raise cause
            except HttpResponseError as error:
                raise RuntimeError("AccountKey=private-token") from error
        except RuntimeError as error:
            details = exception_diagnostics(error)
        self.assertEqual(details[0]["type"], "RuntimeError")
        self.assertEqual(details[1]["status"], 403)
        self.assertEqual(details[1]["code"], "AuthorizationPermissionMismatch")
        self.assertEqual(details[1]["frames"][-1]["file"], "test_errors.py")
        self.assertNotIn("private-token", str(details))
        self.assertNotIn("https://", str(details))
        self.assertNotIn("raise", str(details))

    def test_unexpected_code_payloads_and_cyclic_causes_are_bounded(
        self,
    ) -> None:
        error = RuntimeError("private-message")
        error.error_code = "https://storage/?sig=private-token"
        error.__cause__ = error
        details = exception_diagnostics(error)
        self.assertEqual(len(details), 1)
        self.assertNotIn("code", details[0])
        self.assertNotIn("private", str(details))

    def test_suppressed_context_is_not_logged(self) -> None:
        try:
            try:
                raise ValueError("ignored context")
            except ValueError:
                raise RuntimeError("outer") from None
        except RuntimeError as error:
            details = exception_diagnostics(error)
        self.assertEqual(len(details), 1)


if __name__ == "__main__":
    unittest.main()
