"""Pydantic v2 DTOs for the documents API.

storage_key is never exposed — it's an internal path derived from
{owner_id}/{uuid}.pdf and has no reason to leave the server.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size_bytes: int
    page_count: int | None
    status: str
    error_message: str | None
    summary: str | None
    doc_type: str | None
    key_points: list[str] | None
    extracted_chars: int | None
    created_at: datetime


class DocumentStatusResponse(BaseModel):
    """Polling payload for the dashboard skeleton card — deliberately tiny.

    The frontend hits this every 2s while a document is processing, so it
    carries no summary/doc_type/key_points; GET /documents/{id} returns
    those once status flips to 'ready'.
    """

    model_config = ConfigDict(from_attributes=True)

    status: str
    error_message: str | None


class SearchResultResponse(DocumentResponse):
    """A document plus WHY it matched (PROJECT_PLAN.md §3, §8).

    Extends DocumentResponse rather than defining a parallel shape, so the
    dashboard renders a search hit with the same card component as a normal
    listing and only decorates it with the badge and snippet.

    Phase 11 adds the semantic half of §8: match_reason becomes 'semantic'
    for chunk/summary-embedding hits and snippet carries the best-matching
    passage. Today filename matching is the only implemented branch, so
    match_reason is always 'filename' and snippet echoes the filename —
    the contract is already the final one, only the second branch is missing.
    """

    match_reason: Literal["filename", "semantic"]
    snippet: str


class SignedUrlResponse(BaseModel):
    url: str
    expires_at: datetime
