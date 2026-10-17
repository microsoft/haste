# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Keep transient storage failures distinct from absent catalog/run records."""

from typing import Any

from azure.core.exceptions import ResourceNotFoundError

from .metadata import MetadataProcessor


class CatalogMetadataProcessor(MetadataProcessor):
    def load(self, key: str, data_format: str = "json") -> Any:
        try:
            return super().load(key, data_format)
        except FileNotFoundError as error:
            if error.__cause__ is not None and not isinstance(
                error.__cause__, (ResourceNotFoundError, FileNotFoundError)
            ):
                raise RuntimeError(
                    "Catalog storage could not be read"
                ) from error
            raise
