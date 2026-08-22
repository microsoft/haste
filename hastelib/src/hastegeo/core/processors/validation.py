# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Storage for the layer-scoped Building Validation document.

Wraps MetadataProcessor so the routes that read-then-write this document —
the label save, which must not clobber the configured sample size, and the
config save, which must check the stored labels before shrinking — share one
loader instead of repeating the backend plumbing.
"""

from __future__ import annotations

from typing import Optional

from ..config import Config
from ..models.projects import BuildingValidation
from .metadata import MetadataProcessor


class BuildingValidationProcessor:
    """Loads and saves one image layer's Building Validation document."""

    def __init__(self, project_id: str, config: Optional[Config] = None):
        """Initialize the processor.

        Args:
            project_id: Parent project, used as the partition key.
            config: Configuration instance. Defaults to a new Config().
        """
        self._config = config or Config()
        self._processor = MetadataProcessor(
            data_type=self._config.get_metadata_types().VALIDATION.value,
            partition_key=project_id,
            config=self._config,
        )

    def load(self, image_layer_id: str) -> Optional[dict]:
        """Return the stored document, or None if the layer has none yet."""
        try:
            return self._processor.load(image_layer_id)
        except FileNotFoundError:
            return None

    def save(self, validation: BuildingValidation) -> dict:
        """Persist the document, replacing any existing one.

        Args:
            validation: The complete document to store. This is a wholesale
                replace, so callers are responsible for carrying across any
                field they did not intend to change.

        Returns:
            The stored document as a dict.
        """
        data = validation.model_dump()
        self._processor.save(validation.imageLayerId, data)
        return data
