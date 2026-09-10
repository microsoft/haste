# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Identifiers-only footprint requests, including legacy queue compatibility."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[\w-]+$")
]


class FootprintTilesRequest(BaseModel):
    """A request or a poll for one specific task.

    ``force`` rebuilds a ready/failed layer, never replaces an active job.
    Polls carry ``taskId`` and cannot request a rebuild. ``requestId`` is
    stable across delivery retries; the trigger supplies the Azure message
    ID for manually enqueued requests that omit it.
    """

    model_config = ConfigDict(extra="forbid")

    projectId: Identifier
    imageLayerId: Identifier
    force: StrictBool = False
    requestId: Identifier | None = None
    taskId: Identifier | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_urls(cls, value: Any) -> Any:
        # Accept old messages without retaining or trusting their SAS URLs.
        if isinstance(value, dict):
            return {
                key: item
                for key, item in value.items()
                if key not in ("sourceFootprintsUrl", "buildingFootprintsUrl")
            }
        return value

    @model_validator(mode="after")
    def validate_poll(self) -> "FootprintTilesRequest":
        if self.taskId and self.force:
            raise ValueError("A task poll cannot force a rebuild")
        return self


def parse_tiles_request(body: bytes, message_id: str) -> FootprintTilesRequest:
    """Validate without including payloads or validation details in logs."""
    request = FootprintTilesRequest.model_validate_json(body)
    if request.requestId is None:
        request = FootprintTilesRequest.model_validate(
            {**request.model_dump(), "requestId": message_id}
        )
    return request
