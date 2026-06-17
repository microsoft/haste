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
    predictedDamageLayer: Imagery = Field(default_factory=Imagery)
    predictionsLayer: Imagery = Field(default_factory=Imagery)
    sourceTypePreEvent: Optional[str] = Field(default=None)
    sourceTypePostEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePreEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePostEvent: Optional[str] = Field(default=None)
