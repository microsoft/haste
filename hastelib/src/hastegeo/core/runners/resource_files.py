# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Safe logging helpers for task resource-file configuration."""

from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Redact query and fragment values without changing the URL path."""
    parsed = urlsplit(url)
    query = "REDACTED" if parsed.query else ""
    fragment = "REDACTED" if parsed.fragment else ""
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, fragment)
    )


def redact_resource_files(resource_files: Any) -> Any:
    """Return a log-safe copy of a resource-file dictionary."""
    safe_resources = deepcopy(resource_files)
    if not isinstance(safe_resources, dict):
        return safe_resources
    for file_info in safe_resources.values():
        if not isinstance(file_info, dict):
            continue
        for key, value in file_info.items():
            if key.endswith("_url") and isinstance(value, str):
                file_info[key] = redact_url(value)
    return safe_resources
