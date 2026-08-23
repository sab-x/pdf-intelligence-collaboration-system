"""Pydantic v2 DTOs for the comments API — PROJECT_PLAN.md §3.

Two deliberate choices in CommentResponse:

  * The body of a soft-deleted comment NEVER leaves the server. A tombstone
    is returned with an empty body, so "deleted" means deleted even though
    the row is retained to keep replies attached.

  * `is_document_owner` / `is_mine` / `can_delete` are computed server-side.
    The client has no way to derive them — it doesn't know the document's
    owner_id, and it must not be the thing deciding who may delete what.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CommentCreateRequest(BaseModel):
    body_markdown: str = Field(min_length=1, max_length=5000)
    parent_id: uuid.UUID | None = None
    page_number: int | None = Field(default=None, ge=1)

    @field_validator("body_markdown")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("comment body cannot be empty")
        return stripped


class CommentResponse(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    author_label: str
    body_markdown: str
    page_number: int | None
    created_at: datetime

    is_deleted: bool
    #: The author of this comment is the document's owner.
    is_document_owner: bool
    #: The author of this comment is the caller.
    is_mine: bool
    #: The caller may soft-delete this comment (author, or document owner).
    can_delete: bool

    #: Direct replies. One level only, so a reply always carries an empty list.
    replies: list["CommentResponse"] = Field(default_factory=list)
