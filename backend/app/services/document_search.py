"""Hybrid dashboard search — PROJECT_PLAN.md §8.

    1. filename_hits  ILIKE + trigram similarity ranking
    2. semantic_hits  embed(q) -> best chunk per document, plus the
                      document's own summary_embedding
    3. merge          filename hits first, then semantic by score
    4. each result carries match_reason and, for semantic hits, the
       passage that actually matched

## Why filename hits rank first, unconditionally

Someone typing "Agreement_v3" is navigating, not searching — they know the
file exists and want it now. A semantic hit scoring 0.71 is a *discovery*,
and burying an exact filename match beneath one makes the box feel broken
for the most common interaction. Ranking is by intent, not by score.

## Why both chunks and summary_embedding

Chunks catch a phrase buried on page 12. The summary embedding catches
documents that are *about* the query without containing its words anywhere —
which is precisely the "employment contract" → `Agreement_v3.pdf` case the
brief asks for. Taking the max of the two means a document surfaces whether
the match is local or thematic.

Lives here rather than in the router because it is business logic, and
rather than in retrieval.py because that module is scoped to one document
while this one searches across the owner's whole library.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import Float, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.embeddings import embed_query

logger = logging.getLogger(__name__)

#: Owner-scoped already, so this is a UI guard rather than a security one —
#: a search-as-you-type box should never render thousands of cards.
SEARCH_LIMIT = 50

#: Longest snippet shown under a semantic hit. Long enough to judge
#: relevance, short enough not to turn the card into a wall of text.
SNIPPET_CHARS = 220


@dataclass(frozen=True)
class SemanticHit:
    score: float
    snippet: str


def escape_like(value: str) -> str:
    """Neutralise LIKE wildcards in user input.

    Without this, searching "%" matches every document and "_" matches any
    single character — not a security hole (results stay owner-scoped), but
    silently wrong results for anyone who types a literal % or _.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text: str) -> str:
    """Trim a chunk to a card-sized excerpt, cutting on a word boundary."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= SNIPPET_CHARS:
        return collapsed
    cut = collapsed[:SNIPPET_CHARS]
    space = cut.rfind(" ")
    if space > SNIPPET_CHARS // 2:
        cut = cut[:space]
    return f"{cut}…"


async def filename_hits(db: AsyncSession, owner_id, query: str) -> list[Document]:
    pattern = f"%{escape_like(query)}%"
    result = await db.execute(
        select(Document)
        .where(Document.owner_id == owner_id)
        .where(Document.filename.ilike(pattern, escape="\\"))
        # ILIKE '%…%' is what the gin_trgm_ops index on filename (migration
        # 0002) accelerates. similarity() then ranks "closest name first"
        # instead of the arbitrary order the index scan returns.
        .order_by(
            func.similarity(Document.filename, query).desc(),
            Document.created_at.desc(),
        )
        .limit(SEARCH_LIMIT)
    )
    return list(result.scalars().all())


async def semantic_hits(db: AsyncSession, owner_id, query: str) -> dict:
    """{document_id: SemanticHit} above the similarity threshold.

    Returns {} when the query can't be embedded — search then degrades to
    filenames only, which is a worse result but never an error page.
    """
    vector = await embed_query(query)
    if vector is None:
        logger.warning("search: query embedding failed, filename results only")
        return {}

    threshold = settings.SEMANTIC_SEARCH_THRESHOLD
    hits: dict = {}

    # --- best-matching chunk per document -------------------------------
    #
    # row_number() rather than GROUP BY MAX(score): the score alone would
    # tell us a document matched but not WHICH passage, and the snippet is
    # the whole point — "why did this match?" is what makes the result
    # trustworthy instead of magic.
    distance = DocumentChunk.embedding.cosine_distance(vector)
    ranked = (
        select(
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.content.label("content"),
            (1 - distance).cast(Float).label("score"),
            func.row_number()
            .over(partition_by=DocumentChunk.document_id, order_by=distance.asc())
            .label("rank"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.owner_id == owner_id,
            DocumentChunk.embedding.is_not(None),
        )
        .subquery()
    )

    chunk_rows = await db.execute(
        select(ranked.c.document_id, ranked.c.content, ranked.c.score)
        .where(and_(ranked.c.rank == 1, ranked.c.score > threshold))
        .order_by(ranked.c.score.desc())
        .limit(SEARCH_LIMIT)
    )
    for document_id, content, score in chunk_rows.all():
        hits[document_id] = SemanticHit(score=float(score), snippet=_snippet(content))

    # --- the document's own summary embedding ---------------------------
    #
    # Catches documents that are ABOUT the query without containing its
    # words. Merged by max() so a strong passage match isn't demoted by a
    # weaker thematic one, or vice versa.
    summary_distance = Document.summary_embedding.cosine_distance(vector)
    summary_rows = await db.execute(
        select(Document.id, Document.summary, (1 - summary_distance).cast(Float).label("score"))
        .where(
            Document.owner_id == owner_id,
            Document.summary_embedding.is_not(None),
        )
        .order_by(summary_distance.asc())
        .limit(SEARCH_LIMIT)
    )
    for document_id, summary, score in summary_rows.all():
        score = float(score)
        if score <= threshold:
            continue
        existing = hits.get(document_id)
        if existing is None or score > existing.score:
            hits[document_id] = SemanticHit(
                score=score,
                # Keep a chunk snippet if we already had one — a specific
                # passage is more useful evidence than the summary the user
                # can already see on the card.
                snippet=existing.snippet if existing else _snippet(summary or ""),
            )

    return hits
