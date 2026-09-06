# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Read-only raw prediction generation contracts."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Guid = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    ),
]
ModelId = Annotated[str, Field(strict=True, pattern=r"^[0-9]{1,8}$")]
Revision = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[\w-]+$")
]
RowId = Annotated[int, Field(strict=True, ge=0)]
Binary = Annotated[int, Field(strict=True, ge=0, le=1)]
Score = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class ResultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectId: Guid
    imageLayerId: Guid
    modelId: ModelId

    @model_validator(mode="before")
    @classmethod
    def discard_function_key(cls, value: Any) -> Any:
        # Azure Functions has already authenticated its optional `code`
        # query parameter. It is not part of the business request or queue.
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != "code"}
        return value


class ModelCancellationRequest(BaseModel):
    """Only identifiers from the existing cancellation body are trusted."""

    model_config = ConfigDict(extra="ignore")

    projectId: Guid
    modelId: ModelId


class InferenceQueueRequest(ResultsRequest):
    # Legacy model snapshots may contain URLs. Ignore those fields and load
    # only authoritative metadata; messages without a generation cannot win.
    model_config = ConfigDict(extra="ignore")

    predictionRevision: Revision | None = None
    currentInferenceTaskId: Revision | None = None


class BuildingPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: RowId
    damaged: Binary
    unknown: Score = 0.0
    overtureId: str | None = None


class BuildingPredictionsRequest(ResultsRequest):
    predictions: list[BuildingPrediction]

    @model_validator(mode="after")
    def unique_ids(self) -> "BuildingPredictionsRequest":
        ids = [prediction.id for prediction in self.predictions]
        if len(set(ids)) != len(ids):
            raise ValueError("Prediction IDs must be unique")
        return self


class PredictionAttributes(BaseModel):
    """Validate the uploaded producer contract before publishing readiness."""

    model_config = ConfigDict(extra="ignore")

    schemaVersion: Literal[1]
    predictionRevision: Revision
    flavor: Literal["embedding", "inference"]
    n: RowId
    ids: list[RowId]
    overtureIds: list[str]
    damage: list[Score | None]
    unknown: list[Score | None]
    damaged: list[Binary]
    classes: list[Literal["Damaged", "NotDamaged", "Unknown"]]

    @model_validator(mode="after")
    def consistent_columns(self) -> "PredictionAttributes":
        for column in (
            self.ids,
            self.overtureIds,
            self.damage,
            self.unknown,
            self.damaged,
            self.classes,
        ):
            if len(column) != self.n:
                raise ValueError("Prediction attribute column length mismatch")
        if (
            len(set(self.ids)) != self.n
            or len(set(self.overtureIds)) != self.n
        ):
            raise ValueError("Prediction identities must be unique")
        return self


class ModelArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectId: Guid
    modelId: ModelId | None = None
    imageLayerId: Guid | None = None
    kind: Literal[
        "sidecar", "geojson", "gpkg", "footprint_pmtiles", "prediction_attrs"
    ]
    predictionRevision: Revision | None = None
    version: Literal["0"] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_query(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key != "code"}
            if isinstance(value.get("kind"), str):
                value["kind"] = value["kind"].lower()
        return value

    @model_validator(mode="after")
    def required_owner(self) -> "ModelArtifactRequest":
        if self.kind == "footprint_pmtiles":
            if not self.modelId and not self.imageLayerId:
                raise ValueError("An image layer or model is required")
        elif not self.modelId:
            raise ValueError("A model is required")
        return self
