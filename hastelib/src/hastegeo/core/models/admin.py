# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import List

from pydantic import BaseModel, Field


class SourceType(BaseModel):
    sourceTypeId: int = Field(default=0)
    name: str = Field(default=None)
    baseURL: str = Field(default=None)
    creationDate: str = Field(default=None)


class BaseModels(BaseModel):
    baseModelId: str = Field(default=0)
    name: str = Field(default=None)
    sourceURL: str = Field(default=None)
    creationDate: str = Field(default=None)


class DrawingTools(BaseModel):
    polygon: bool = Field(default=False)
    rectangle: bool = Field(default=False)
    circle: bool = Field(default=False)


class Grid(BaseModel):
    gridStrokeColor: str = Field(default=None)


class DefaultPrimaryClass(BaseModel):
    name: str = Field(default=None)
    color: str = Field(default=None)


class LabelingToolSettings(BaseModel):
    drawingTools: DrawingTools = Field(default_factory=DrawingTools)
    grid: Grid = Field(default_factory=Grid)
    defaultPrimaryClasses: List[DefaultPrimaryClass] = Field(
        default_factory=list
    )
    tileServerSettings: str = Field(default=None)


class AdminConfig(BaseModel):
    sourceTypes: List[SourceType] = Field(default_factory=list)
    baseModels: List[BaseModels] = Field(default_factory=list)
    labelingToolSettings: LabelingToolSettings = Field(
        default_factory=LabelingToolSettings
    )
