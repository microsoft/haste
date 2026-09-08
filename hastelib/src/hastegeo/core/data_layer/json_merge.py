# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Conditional top-level JSON updates for blob-backed metadata."""

import json
from typing import Any, Callable

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)


def merge_blob_json(
    blob: Any,
    fields: dict,
    index_metadata: Callable[[dict], dict] | None = None,
) -> dict:
    for attempt in range(5):
        try:
            download = blob.download_blob()
            current = json.loads(download.readall())
            etag = download.properties.etag
        except ResourceNotFoundError:
            current, etag = {}, None
        merged = {**current, **fields}
        options = (
            {
                "overwrite": True,
                "etag": etag,
                "match_condition": MatchConditions.IfNotModified,
            }
            if etag
            else {"overwrite": False}
        )
        if index_metadata:
            options["metadata"] = index_metadata(merged)
        try:
            blob.upload_blob(json.dumps(merged), **options)
            return merged
        except (ResourceModifiedError, ResourceExistsError):
            if attempt == 4:
                raise
    raise AssertionError("Unreachable")
