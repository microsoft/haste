from typing import Any

from pydantic import BaseModel, Field

from .publishing import ProviderInfo


class SessionUser(BaseModel):
    userId: str
    identityId: str
    userRoles: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    status: str


class SessionPublishing(BaseModel):
    publishingEnabled: bool
    providers: list[ProviderInfo] = Field(default_factory=list)


class SessionBootstrap(BaseModel):
    user: SessionUser
    publishing: SessionPublishing
