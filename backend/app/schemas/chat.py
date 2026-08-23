"""Chat DTOs — PROJECT_PLAN.md §3, §7."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    #: Omit to start a new conversation. When supplied it is verified to
    #: belong to the calling principal — document access alone does not
    #: authorise reading someone else's session.
    session_id: uuid.UUID | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message cannot be empty")
        return stripped


class Citation(BaseModel):
    """One excerpt an answer was grounded in."""

    chunk_id: uuid.UUID
    page_start: int
    page_end: int
    #: The excerpt itself, for the "grounded in" expander. This is what
    #: makes the retrieval visible instead of asking the reader to trust it.
    excerpt: str
    #: "vector", "text", or both — which retriever surfaced this chunk.
    matched_by: list[str]


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] | None
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    session_id: uuid.UUID
    messages: list[ChatMessageResponse]
