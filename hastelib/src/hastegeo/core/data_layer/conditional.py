# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from typing import Any, TypeAlias

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.storage.blob import BlobClient

JsonDocument: TypeAlias = dict[str, Any] | list[Any]


class RevisionConflictError(RuntimeError):
    """A document changed between its read and conditional write."""


def decode_document(contents: bytes | str) -> JsonDocument:
    document = json.loads(contents)
    if isinstance(document, str):
        document = json.loads(document)
    if not isinstance(document, (dict, list)):
        raise ValueError("Metadata must contain a JSON object or array")
    return document


def read_blob_document(client: BlobClient) -> tuple[JsonDocument, str]:
    try:
        download = client.download_blob()
        return decode_document(download.readall()), download.properties.etag
    except ResourceNotFoundError as error:
        raise FileNotFoundError("Metadata document not found") from error


def write_blob_document(
    client: BlobClient,
    document: JsonDocument,
    expected_version: str | None,
    metadata: dict[str, str] | None = None,
) -> None:
    conditions = (
        {
            "etag": expected_version,
            "match_condition": MatchConditions.IfNotModified,
        }
        if expected_version is not None
        else {}
    )
    try:
        client.upload_blob(
            json.dumps(document),
            overwrite=expected_version is not None,
            metadata=metadata,
            **conditions,
        )
    except (
        ResourceExistsError,
        ResourceModifiedError,
        ResourceNotFoundError,
    ) as error:
        raise RevisionConflictError("Metadata revision changed") from error
