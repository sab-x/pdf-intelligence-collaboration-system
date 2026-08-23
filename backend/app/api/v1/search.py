"""Dashboard search — PROJECT_PLAN.md §3, §8.

Its own router rather than a route on documents.py, because that router is
mounted at prefix="/documents" and this endpoint is /search (matching the
layout in §1, which lists api/v1/search.py alongside documents.py).

§8 describes a hybrid endpoint: filename hits ranked first, then semantic
hits from document_chunks / summary_embedding above a similarity threshold.
Phase 11 adds that second half. What exists today is the filename half, but
the RESPONSE CONTRACT is already the final one — every result carries
match_reason and snippet — so adding semantic hits later is purely additive
and the dashboard needs no reshaping.
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require_user
from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import DocumentResponse, SearchResultResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

# A query can only ever surface the caller's own documents, so an unbounded
# result set is already owner-sized — but a cap keeps one pathological
# account from returning thousands of rows to a search-as-you-type box.
_SEARCH_LIMIT = 50


def _escape_like(value: str) -> str:
    """Neutralise LIKE wildcards in user input.

    Without this, searching "%" matches every document and "_" matches any
    single character — not a security hole (results stay owner-scoped), but
    silently wrong results for anyone who types a literal % or _.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search", response_model=list[SearchResultResponse])
async def search_documents(
    q: str = Query("", description="Search text; matched against filenames."),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchResultResponse]:
    query = q.strip()
    if not query:
        # A search-as-you-type box hits this on every clear/backspace-to-empty.
        # Empty results beat a 422 the UI would have to special-case.
        return []

    pattern = f"%{_escape_like(query)}%"
    result = await db.execute(
        select(Document)
        .where(Document.owner_id == principal.user_id)
        .where(Document.filename.ilike(pattern, escape="\\"))
        # ILIKE '%…%' is what the gin_trgm_ops index on filename (migration
        # 0002) accelerates. similarity() then ranks "closest name first"
        # instead of the arbitrary order the index scan returns.
        .order_by(
            func.similarity(Document.filename, query).desc(),
            Document.created_at.desc(),
        )
        .limit(_SEARCH_LIMIT)
    )

    # Building the document half via DocumentResponse keeps that field list
    # in exactly one place — adding a column there must not require editing
    # this module too.
    return [
        SearchResultResponse(
            **DocumentResponse.model_validate(doc).model_dump(),
            match_reason="filename",
            # Phase 11: the best-matching passage for semantic hits. Until
            # then the filename IS the matched text, so echoing it keeps the
            # UI's snippet line meaningful rather than blank.
            snippet=doc.filename,
        )
        for doc in result.scalars().all()
    ]
