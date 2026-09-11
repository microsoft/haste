# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Response models for route-specific loading endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class ActiveJobIndicator(BaseModel):
    """Progress fields consumed by the dashboard status indicator."""

    id: str
    currentStep: int | None = None
    totalSteps: int | None = None
    progressPct: float | None = None
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
