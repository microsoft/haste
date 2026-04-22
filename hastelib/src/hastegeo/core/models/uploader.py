# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import Optional

from pydantic import BaseModel, Field


class FileUploadRequest(BaseModel):
    projectId: Optional[str] = Field(default=None)
    fileId: Optional[str] = Field(default=None)
    totalChunks: Optional[str] = Field(default=None)
    chunkNumber: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    statusMessage: Optional[str] = Field(default=None)
    outputUrl: Optional[str] = Field(default=None)
    updatedDate: Optional[str] = Field(default=None)
