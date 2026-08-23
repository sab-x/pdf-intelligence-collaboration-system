"""Pydantic v2 DTOs for sharing — PROJECT_PLAN.md §3.

Email is validated with the same regex used in schemas/auth.py rather than
pydantic's EmailStr, because EmailStr pulls in the `email-validator` package
and this project doesn't depend on it. Matching the existing approach keeps
the dependency set unchanged.

SharePreviewResponse — what an anonymous visitor sees before identifying
themselves — is deliberately thin. Filename and page count are enough to
show "someone shared this with you"; the summary and the document id are
withheld until a guest session exists, so an unopened link leaks as little
as possible if it's forwarded or lands in a log.
"""
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SharePermission = Literal["view", "comment"]


class ShareLinkCreateRequest(BaseModel):
    permission: SharePermission = "comment"
    #: Captured and stored. Sending the invitation is out of scope (README
    #: trade-off), so this is metadata for the owner, not a delivery trigger.
    invited_email: str | None = Field(default=None, max_length=320)
    #: Omit for a link that never expires. Capped at 30 days.
    expires_in_hours: int | None = Field(default=None, ge=1, le=720)

    @field_validator("invited_email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class ShareLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    token: str
    #: Fully-qualified link the owner copies. Built from FRONTEND_URL so it
    #: points at the deployed app, not at the API.
    url: str
    permission: SharePermission
    invited_email: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    last_accessed_at: datetime | None
    view_count: int
    created_at: datetime
    #: Computed server-side: not revoked and not past expiry. The client
    #: should not be re-deriving this from two nullable timestamps.
    is_active: bool


class SharePreviewResponse(BaseModel):
    """Public, unauthenticated view of a share link."""

    filename: str
    page_count: int | None
    permission: SharePermission
    #: Display name of the person who shared it, for "N shared this with you".
    shared_by: str


class GuestSessionCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("display_name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("display name cannot be empty")
        return stripped


class GuestSessionResponse(BaseModel):
    """The guest's credentials plus everything the share page needs next.

    document_id is returned here and not in the preview: it's the point at
    which the visitor has actually been granted access, so it's the first
    moment the document's identifier is theirs to know.
    """

    guest_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    document_id: uuid.UUID
    permission: SharePermission
    display_name: str
