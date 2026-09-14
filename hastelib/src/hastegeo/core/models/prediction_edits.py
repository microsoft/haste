# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Version metadata and strictly validated editing wire contracts."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from .prediction_results import (
    Binary,
    Guid,
    ModelId,
    PositiveVersion,
    PredictionAttributes,
    QueryVersion,
    ResultsRequest,
    Revision,
    RowId,
    Score,
    VersionNumber,
)

PredictionClass = Literal["Damaged", "NotDamaged", "Unknown"]


def canonical_request_id(value: Any) -> str:
    return str(UUID(str(value)))


StoredRequestId = Annotated[str, BeforeValidator(canonical_request_id)]


class EditedPredictionVersion(BaseModel):
    """Confirmed append-only metadata; old #136 entries remain readable."""

    version: PositiveVersion
    gpkgUrl: str
    predictionAttrsUrl: str | None = None
    createdAt: str | None = None
    createdBy: str | None = None
    threshold: Score | None = None
    unknownThreshold: Score | None = None
    editedCount: RowId = 0
    buildingCount: RowId | None = None
    sourceGpkgUrl: str | None = None
    sourcePredictionRevision: Revision | None = None
    baseVersion: VersionNumber | None = None
    clientRequestId: StoredRequestId | None = None
    flavor: Literal["embedding", "inference"] | None = None
    overridesApplied: RowId | None = None
    requestFingerprint: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ] | None = None


class PredictionOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: RowId
    edited_class: PredictionClass = Field(alias="class")


class SaveEditedPredictionsRequest(ResultsRequest):
    predictionRevision: Revision
    baseVersion: VersionNumber
    clientRequestId: UUID
    threshold: Score
    unknownThreshold: Score
    overrides: list[PredictionOverrideRequest]

    @model_validator(mode="after")
    def unique_overrides(self) -> "SaveEditedPredictionsRequest":
        ids = [row.id for row in self.overrides]
        if len(ids) != len(set(ids)):
            raise ValueError("Override row IDs must be unique")
        return self


class PredictionSelectionRequest(ResultsRequest):
    version: QueryVersion | None = None
    predictionRevision: Revision | None = None


class PredictionVersionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectId: Guid
    modelId: ModelId
    imageLayerId: Guid | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_function_key(cls, value: Any) -> Any:
        return ResultsRequest.discard_function_key(value)


class PredictionReportRequest(PredictionSelectionRequest):
    # The raw report defaults are independent of the editor's zero defaults.
    threshold: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.1
    minAreaM2: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 50


class EditedPredictionAttributes(PredictionAttributes):
    """Edited decisions may classify null/unscored raw rows: do not infer
    effective classes from the preserved raw scores or binary damaged bit.
    """

    predictionVersion: PositiveVersion
    isEdited: Literal[True]
    modelClasses: list[PredictionClass]
    overrideClasses: list[PredictionClass | None]
    threshold: Score
    unknownThreshold: Score
    damaged: list[Binary]

    @model_validator(mode="after")
    def consistent_edited_columns(self) -> "EditedPredictionAttributes":
        if (
            len(self.modelClasses) != self.n
            or len(self.overrideClasses) != self.n
        ):
            raise ValueError("Edited attribute column length mismatch")
        for effective, override in zip(self.classes, self.overrideClasses):
            if override is not None and effective != override:
                raise ValueError(
                    "Effective class does not match explicit assignment"
                )
        return self


class SavedPredictionResponse(BaseModel):
    version: PositiveVersion
    predictionRevision: Revision
    gpkgUrl: str
    predictionAttrsUrl: str
    buildingCount: RowId
    editedCount: RowId
    overridesApplied: RowId | None = None
