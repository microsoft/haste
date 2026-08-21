# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""HTTP wire contracts for the prediction editor.

These models describe the *request bodies* the ``hastefuncapi`` routes
accept — they exist so a malformed body is rejected at the HTTP boundary
with a 400 instead of reaching the geospatial code. They deliberately
carry no behavior beyond validation: every decision they feed (class
derivation, thresholding, versioning, blob writes, queueing) lives in
``hastegeo.core.processors.prediction_edits`` and
``hastegeo.core.processors.prediction_tiles``.

They live here rather than in ``function_app.py`` because
``api/hastefuncapi/function_app.py`` must contain only thin HTTP
wrappers (see ``AGENTS.md``), and next to each other rather than in
``projects.py`` because that module holds *persisted document schemas*
(``Project``/``ImageLayer``/``Model``/``EditedPredictionVersion``) while
these are transport-only shapes — the same split ``publishing.py``
already makes with ``PublishRequest`` versus ``PublishedDataset``.
"""
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..utils.assessment import DAMAGED, NOT_DAMAGED, UNKNOWN

# Strict allowlist patterns, kept identical to the ones the API layer
# applies to query-string parameters (``_GUID_RE`` /
# ``_SHORT_INT_ID_RE`` in ``function_app.py``): bounded length and
# character set to defend against injection, path traversal, and
# oversized inputs. modelId is a MetadataUtils.generate_short_int_id()
# value (currently 4 zero-padded digits, e.g. "5557"), not a GUID.
GUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SHORT_INT_ID_PATTERN = r"^[0-9]{1,8}$"

# The only classes an analyst may assign to a building.
PREDICTION_EDIT_CLASSES = (DAMAGED, NOT_DAMAGED, UNKNOWN)

# Where the editor's damage slider starts. 0.0 reproduces what each
# producer already stored: the inference GeoPackage derives its own
# ``damaged`` column from ``damage_pct_0m > 0``, and the embedding
# producer only ever writes 0.0/1.0. Comparisons downstream are strictly
# greater-than, so 0.0 keeps pristine buildings out of the damaged
# bucket.
PREDICTION_EDIT_DEFAULT_THRESHOLD = 0.0


class PredictionOverrideRequest(BaseModel):
    """One analyst class override: ``{"id": <row index>, "class": ...}``.

    ``id`` is the zero-based row index of the building in the prediction
    GeoPackage — the join key the whole prediction pipeline uses.
    """

    model_config = ConfigDict(populate_by_name=True)

    rowIndex: int = Field(alias="id", ge=0)
    editedClass: str = Field(alias="class")

    @field_validator("editedClass")
    @classmethod
    def _known_class(cls, value: str) -> str:
        if value not in PREDICTION_EDIT_CLASSES:
            raise ValueError(
                "must be one of " + ", ".join(PREDICTION_EDIT_CLASSES)
            )
        return value


class EditedPredictionsRequest(BaseModel):
    """Validated body of a ``PutEditedPredictions`` request."""

    projectId: str = Field(pattern=GUID_PATTERN)
    imageLayerId: str = Field(pattern=GUID_PATTERN)
    modelId: str = Field(pattern=SHORT_INT_ID_PATTERN)
    threshold: float = Field(
        default=PREDICTION_EDIT_DEFAULT_THRESHOLD, ge=0.0, le=1.0
    )
    unknownThreshold: float = Field(default=0.0, ge=0.0, le=1.0)
    overrides: List[PredictionOverrideRequest] = Field(default_factory=list)

    @field_validator("overrides")
    @classmethod
    def _reject_duplicate_ids(
        cls, value: List[PredictionOverrideRequest]
    ) -> List[PredictionOverrideRequest]:
        """Two classes for one building is a client bug, not a merge."""
        seen: set[int] = set()
        for override in value:
            if override.rowIndex in seen:
                raise ValueError(f"duplicate id {override.rowIndex}")
            seen.add(override.rowIndex)
        return value


class PreparePredictionTilesRequest(BaseModel):
    """Validated body of a ``PutPreparePredictionTilesQueueMessage``.

    Asks for the footprint PMTiles of ``imageLayerId`` and the prediction
    attribute sidecar of ``modelId`` to be built. ``force`` rebuilds them
    even when both already exist — used after predictions are
    regenerated, which leaves stale artifacts behind.
    """

    projectId: str = Field(pattern=GUID_PATTERN)
    imageLayerId: str = Field(pattern=GUID_PATTERN)
    modelId: str = Field(pattern=SHORT_INT_ID_PATTERN)
    force: bool = Field(default=False)
