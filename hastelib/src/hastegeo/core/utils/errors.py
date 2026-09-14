# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Human-readable rendering of exceptions surfaced to end users.

Azure SDK errors stringify to a debug dump — an ``azure.batch``
``BatchErrorException`` renders as::

    Request encountered an exception.
    Code: NodeNotReady
    Message: {'additional_properties': {}, 'lang': 'en-US', 'value': 'Node is
    not able to perform the requested operations in its current
    state\\nRequestId:...\\nTime:...'}

That text ends up in ``statusMessage`` and then verbatim in the UI. This module
reduces such errors to ``Code: message`` so the status dialog stays readable.

The Azure error shape is matched structurally (``.error.code`` /
``.error.message.value``) rather than by ``isinstance``, so this stays a leaf
utility with no SDK import.
"""

import re
import traceback
from pathlib import Path
from typing import Any, Optional

# RequestId/Time are appended by the service to the message body; they are
# useful in logs but noise in a UI status message.
_SERVICE_TRAILER_MARKERS = ("\nRequestId:", "\nTime:")


def exception_diagnostics(exc: BaseException) -> list[dict[str, Any]]:
    """Describe failure locations/SDK codes without messages or payloads."""
    chain = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        entry: dict[str, Any] = {"type": type(current).__name__}
        status = getattr(current, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            entry["status"] = status
        code = getattr(current, "error_code", None)
        if code is None:
            code = getattr(getattr(current, "error", None), "code", None)
        if isinstance(code, str) and re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,99}", code
        ):
            entry["code"] = code
        frames = traceback.extract_tb(current.__traceback__)
        if len(frames) > 12:
            frames = frames[:6] + frames[-6:]
        entry["frames"] = [
            {
                "file": Path(frame.filename).name,
                "line": frame.lineno,
                "function": frame.name,
            }
            for frame in frames
        ]
        chain.append(entry)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain


def _unwrap_message(message: Any) -> Optional[str]:
    """Return the human-readable text of an Azure ``ErrorMessage``-like value."""
    value = getattr(message, "value", None)
    if isinstance(value, str):
        return value
    return message if isinstance(message, str) else None


def _strip_service_trailer(text: str) -> str:
    for marker in _SERVICE_TRAILER_MARKERS:
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    return text.strip()


def describe_exception(exc: BaseException) -> str:
    """Return a short, user-facing description of ``exc``.

    Azure-style errors become ``"<Code>: <message>"``; everything else falls
    back to ``str(exc)``. The exception type is used when there is no message
    at all, so the result is never an empty string.
    """
    error = getattr(exc, "error", None)
    code = getattr(error, "code", None) if error is not None else None
    message = (
        _unwrap_message(getattr(error, "message", None))
        if error is not None
        else None
    )

    if isinstance(code, str) and code:
        if message:
            return f"{code}: {_strip_service_trailer(message)}"
        return code
    if message:
        return _strip_service_trailer(message)

    text = str(exc).strip()
    return text or type(exc).__name__
