# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import Optional

from pydantic import BaseModel, Field


class Imagery(BaseModel):
    url: str = Field(default="")
    tms: bool = Field(default=False)
    attribution: str = Field(default="AI For Good Lab")
    minZoom: int = Field(default=12)
    maxNativeZoom: int = Field(default=20)
    maxZoom: int = Field(default=21)
    bounds: list = Field(default_factory=list)


class Visualizer(BaseModel):
    projectId: str = Field(default="")
    imageLayerId: str = Field(default="")
    modelId: str = Field(default="")
    projectName: str = Field(default="")
    studyArea: list = Field(default_factory=list)
    eventDate: Optional[str] = Field(default=None)
    predictedDamageImageryDownloadUrl: str = Field(default="")
    preDisasterImagery: Imagery = Field(default_factory=Imagery)
    postDisasterImagery: Imagery = Field(default_factory=Imagery)
    predictedDamageLayer: Optional[Imagery] = Field(default=None)
    predictionsLayer: Optional[Imagery] = Field(default=None)
    footprintTilesUrl: Optional[str] = Field(default=None)
    predictionAttrsUrl: Optional[str] = Field(default=None)
    gpkgUrl: Optional[str] = Field(default=None)
    predictionRevision: Optional[str] = Field(default=None)
    flavor: Optional[str] = Field(default=None)
    supportsThreshold: bool = Field(default=False)
    defaultThreshold: float = Field(default=0)
    defaultUnknownThreshold: float = Field(default=0)
    buildingCount: Optional[int] = Field(default=None)
    predictionsReady: bool = Field(default=False)
    predictionsReadiness: dict = Field(default_factory=dict)
    rawPredictionsReady: bool = Field(default=False)
    sourceTypePreEvent: Optional[str] = Field(default=None)
    sourceTypePostEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePreEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePostEvent: Optional[str] = Field(default=None)
