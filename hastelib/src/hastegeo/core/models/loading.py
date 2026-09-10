# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Response models for route-specific loading endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from .projects import LabelProject, PrimaryClass


class LabelingImageLayer(BaseModel):
    """Allowlisted image-layer fields required by the labeling UI."""

    imageLayerId: str
    name: str | None = None
    sourceTypePostEvent: str | None = None


class LabelingWorkspace(BaseModel):
    """Data required to initialize one standard labeling workspace."""

    labelProject: LabelProject
    imageLayer: LabelingImageLayer
    eventTypes: list[str] = Field(default_factory=list)
    primaryClasses: list[PrimaryClass] = Field(default_factory=list)


class ActiveJobIndicator(BaseModel):
    """Progress fields consumed by the dashboard status indicator."""

    id: str
    currentStep: int = 0
    totalSteps: int = 0
    progressPct: float = 0.0
    status: str
    statusMessage: str = ""
    prefix: str
    contextLabel: str


class ActiveJob(BaseModel):
    """Compact active-job representation for the dashboard."""

    key: str
    kind: Literal["Imagery", "Training", "Inference"]
    projectName: str
    name: str
    target: str
    indicator: ActiveJobIndicator


class ActiveJobs(BaseModel):
    """Active jobs across candidate projects."""

    jobs: list[ActiveJob] = Field(default_factory=list)
