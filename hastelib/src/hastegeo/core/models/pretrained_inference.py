# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Catalog recipes and inference-only submission contracts."""

import math
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Guid = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    ),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CatalogInferenceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal[1] = 1
    adapter: Literal["legacy_haste", "dinov3_upernet"]
    checkpointFilePath: str = Field(min_length=1, max_length=4096)
    checkpointSha256: Digest | None = None
    checkpointEtag: str | None = None
    backboneConfigPath: str | None = None
    backboneConfigSha256: Digest | None = None
    backbone: str | None = None
    labelGrouping: Literal["any"] | None = None
    sourceRevision: str | None = None
    sourceUrl: str | None = None
    inputKind: Literal["raw", "rgb"] = "raw"
    numChannels: int = Field(gt=0, le=64)
    normalizationMeans: list[float]
    normalizationStds: list[float]
    experimentConfig: dict[str, Any] | None = None
    patchSize: int = Field(default=512, ge=32, le=4096)
    padding: int = Field(default=64, ge=0)
    batchSize: int = Field(default=8, ge=1, le=64)
    numWorkers: int = Field(default=2, ge=1, le=32)
    prefetchFactor: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def compatible_recipe(self) -> "CatalogInferenceSpec":
        if self.patchSize % 16 or self.padding * 2 >= self.patchSize:
            raise ValueError("Invalid inference patch/padding")
        if (
            len(self.normalizationMeans) != self.numChannels
            or len(self.normalizationStds) != self.numChannels
            or not all(math.isfinite(x) for x in self.normalizationMeans)
            or not all(
                math.isfinite(x) and x > 0 for x in self.normalizationStds
            )
        ):
            raise ValueError("Invalid model normalization")
        if self.adapter == "dinov3_upernet":
            if (
                self.inputKind != "rgb"
                or self.numChannels != 3
                or not self.checkpointSha256
                or not self.backboneConfigPath
                or not self.backboneConfigSha256
                or self.labelGrouping != "any"
                or self.backbone
                not in {
                    "dinov3_vits16",
                    "dinov3_vitb16",
                    "dinov3_vitl16",
                    "dinov3_vitl16_sat",
                }
                or self.normalizationMeans != [0.485, 0.456, 0.406]
                or self.normalizationStds != [0.229, 0.224, 0.225]
            ):
                raise ValueError(
                    "DINOv3 requires a pinned RGB8/any-damage recipe"
                )
        elif self.experimentConfig is None:
            raise ValueError(
                "HASTE checkpoints require their source experiment configuration"
            )
        return self


class CatalogInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    projectId: Guid
    imageLayerId: Guid
    baseModelName: str = Field(min_length=1, max_length=100)
    clientRequestId: UUID
    name: str | None = Field(default=None, min_length=1, max_length=100)
