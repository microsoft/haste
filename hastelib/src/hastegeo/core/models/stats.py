# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import List, Optional

from pydantic import BaseModel, Field


class ImageLayerStats(BaseModel):
    imageLayerId: Optional[str] = Field(default=None)
    labelsCount: Optional[int] = Field(default=0)


class ProjectStats(BaseModel):
    projectId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    imageLayerStats: Optional[List[ImageLayerStats]] = Field(
        default_factory=list
    )  # collects all image layer ids and count of labels added to the project
    modelIds: Optional[List[str]] = Field(
        default_factory=list
    )  # collects all model ids added to the project
    affectedCountries: Optional[List[str]] = Field(default_factory=list)
    imageLayerCount: Optional[int] = Field(default=0)
    modelsCount: Optional[int] = Field(default=0)
    labelsCount: Optional[int] = Field(default=0)


class StatsRequest(BaseModel):
    action: Optional[str] = Field(default=None)
    projectId: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    creationDate: Optional[str] = Field(default=None)
    imageLayerStats: Optional[ImageLayerStats] = Field(
        default=None
    )  # only one image layer updated per message
    modelIds: Optional[List[str]] = Field(default_factory=list)
    affectedCountries: Optional[List[str]] = Field(default_factory=list)


class ProjectsSummary(BaseModel):
    projects: Optional[List[ProjectStats]] = Field(default_factory=list)
