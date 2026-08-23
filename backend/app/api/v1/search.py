"""Dashboard search — PROJECT_PLAN.md §3, §8.

Its own router rather than a route on documents.py, because that router is
mounted at prefix="/documents" and this endpoint is /search (matching the
layout in §1, which lists api/v1/search.py alongside documents.py).

HTTP concerns only. The hybrid ranking lives in
services/document_search.py — this module decides status codes and shapes
the response, nothing more.
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require_user
from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import DocumentResponse, SearchResultResponse
from app.services.document_search import SEARCH_LIMIT, filename_hits, semantic_hits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchResultResponse])
async def search_documents(
    q: str = Query("", description="Search text. Matched by filename and by meaning."),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchResultResponse]:
    """Hybrid search over the caller's own documents.

    Filename matches first (someone typing a filename is navigating, not
    discovering), then semantic matches by score. Every result says why it
    matched.
    """
    query = q.strip()
    if not query:
        # A search-as-you-type box hits this on every clear/backspace-to-empty.
        # Empty results beat a 422 the UI would have to special-case.
        return []

    by_filename = await filename_hits(db, principal.user_id, query)
    by_meaning = await semantic_hits(db, principal.user_id, query)

    # Building the document half via DocumentResponse keeps that field list
    # in exactly one place — adding a column there must not require editing
    # this module too.
    results = [
        SearchResultResponse(
            **DocumentResponse.model_validate(doc).model_dump(),
            match_reason="filename",
            # The filename IS the matched text here, so echoing it keeps the
            # snippet line meaningful rather than blank.
            snippet=doc.filename,
        )
        for doc in by_filename
    ]

    # A document already surfaced by filename is not repeated as a semantic
    # hit — one card, and "matched: filename" is the more actionable reason
    # to show for it.
    already_shown = {doc.id for doc in by_filename}
    remaining = {
        document_id: hit
        for document_id, hit in by_meaning.items()
        if document_id not in already_shown
    }

    if remaining:
        rows = await db.execute(select(Document).where(Document.id.in_(remaining)))
        documents = {doc.id: doc for doc in rows.scalars().all()}

        for document_id, hit in sorted(
            remaining.items(), key=lambda item: item[1].score, reverse=True
        ):
            doc = documents.get(document_id)
            if doc is None:
                continue
            results.append(
                SearchResultResponse(
                    **DocumentResponse.model_validate(doc).model_dump(),
                    match_reason="semantic",
                    snippet=hit.snippet,
                )
            )

    logger.info(
        "search: q=%r filename=%d semantic=%d total=%d",
        query,
        len(by_filename),
        len(remaining),
        len(results),
    )
    return results[:SEARCH_LIMIT]
