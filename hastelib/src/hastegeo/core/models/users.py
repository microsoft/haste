# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import List, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    userId: Optional[
        str
    ] = None  # is populated with email instead of generated id
    objectId: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    userRoles: Optional[List[str]] = Field(default_factory=list)
    identityProvider: Optional[str] = None
    settings: Optional[dict] = Field(default_factory=dict)
    status: Optional[str] = None
    added_by: Optional[str] = None
    added_on: Optional[str] = None
    updated_on: Optional[str] = None
    deleted: bool = False


class Users(BaseModel):
    users: Optional[List[User]] = Field(default_factory=list)


class Invite(BaseModel):
    email_id: str
    roles: List[str] = Field(default_factory=list)
    invitation_link: str = None
    email_sent: bool = False
    error: str = None


class Invites(BaseModel):
    results: List[Invite] = Field(default_factory=list)


class AddUsersRequest(BaseModel):
    emails: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    added_by: str
