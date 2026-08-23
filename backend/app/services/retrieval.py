"""Hybrid retrieval — PROJECT_PLAN.md §7.

    1. QUERY REWRITE  (only when there is prior conversation)
    2. VECTOR SEARCH  top 12 by cosine distance
    3. KEYWORD SEARCH top 12 by ts_rank
    4. FUSE           reciprocal rank fusion, score = Σ 1/(60 + rank)
    5. TAKE           top 6, reordered by position in the document

## Why hybrid rather than just vectors

Embeddings are good at meaning and bad at exact identifiers. "Section 8.2",
"₹4,50,000", "Clause XI" — the literal strings people actually ask contracts
about — are precisely what a 768-dimension projection blurs away. Postgres
full-text nails those and is hopeless at paraphrase. Neither alone is
adequate; the union covers both failure modes.

## Why RRF rather than blending scores

Cosine distance and ts_rank are not on a common scale and their
distributions differ per query, so any weighted sum needs tuning that would
be fitted to whatever documents happened to be at hand. RRF discards the
scores entirely and fuses on RANK, which is scale-free and needs no tuning.
k=60 is the value from the original paper and is not sensitive.

## Why the final order is document order, not relevance order

The top 6 go into the prompt as context. Presenting them in the order they
appear in the document lets the model follow the document's own narrative;
relevance order interleaves page 9 before page 2 and produces answers that
read as disjointed. Ranking decides WHICH chunks; position decides how they
are PRESENTED.
"""
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.document_chunk import DocumentChunk
from app.services.ai import rewrite_followup_query
from app.services.embeddings import embed_query

logger = logging.getLogger(__name__)

#: The constant from the RRF paper. Damps the contribution of top ranks so a
#: chunk ranked #1 in one list doesn't automatically beat a chunk ranked #2
#: in both.
RRF_K = 60

_TS_CONFIG = "english"


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk selected for the prompt, with why it was selected."""

    id: str
    content: str
    page_start: int
    page_end: int
    chunk_index: int
    #: Which retrievers surfaced it — "vector", "text", or both. Shown in the
    #: "grounded in" expander, and genuinely useful when debugging a bad
    #: answer: a result found only by text search usually means the question
    #: hinged on an exact string.
    matched_by: tuple[str, ...]

    @property
    def citation(self) -> str:
        if self.page_start == self.page_end:
            return f"[p. {self.page_start}]"
        return f"[pp. {self.page_start}-{self.page_end}]"


async def _vector_candidates(
    db: AsyncSession, document_id: str, query: str, limit: int
) -> list[DocumentChunk]:
    """Top-N by cosine distance. Empty when the query can't be embedded or
    the document has no vectors — the caller still has the text half.
    """
    vector = await embed_query(query)
    if vector is None:
        logger.warning("retrieval: query embedding failed, falling back to text only")
        return []

    stmt = (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document_id,
            # NULL embeddings are the degraded-ingestion case from Phase 9.
            # Excluding them explicitly rather than letting the operator
            # decide keeps NULL ordering out of the picture entirely.
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(DocumentChunk.embedding.cosine_distance(vector))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _text_candidates(
    db: AsyncSession, document_id: str, query: str, limit: int
) -> list[DocumentChunk]:
    """Top-N by ts_rank over the generated tsvector column.

    plainto_tsquery, not to_tsquery: the input is a user's sentence, and
    to_tsquery would raise a syntax error on ordinary punctuation. Anything
    that reduces to an empty query returns nothing rather than erroring.
    """
    tsquery = func.plainto_tsquery(_TS_CONFIG, query)
    rank = func.ts_rank(DocumentChunk.tsv, tsquery).cast(Float)

    stmt = (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tsv.op("@@")(tsquery),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _fuse(
    vector_hits: list[DocumentChunk],
    text_hits: list[DocumentChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Reciprocal rank fusion, then reorder by document position."""
    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    chunks: dict[str, DocumentChunk] = {}

    for label, hits in (("vector", vector_hits), ("text", text_hits)):
        for rank, chunk in enumerate(hits, start=1):
            key = str(chunk.id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            sources.setdefault(key, set()).add(label)
            chunks[key] = chunk

    best = sorted(scores, key=lambda key: scores[key], reverse=True)[:top_k]

    # Selected by score, presented in document order — see the module
    # docstring.
    selected = sorted(best, key=lambda key: chunks[key].chunk_index)

    return [
        RetrievedChunk(
            id=key,
            content=chunks[key].content,
            page_start=chunks[key].page_start,
            page_end=chunks[key].page_end,
            chunk_index=chunks[key].chunk_index,
            matched_by=tuple(sorted(sources[key])),
        )
        for key in selected
    ]


async def retrieve(
    *,
    document_id: str,
    message: str,
    history: list[tuple[str, str]] | None = None,
) -> tuple[list[RetrievedChunk], str]:
    """Find the chunks that should answer `message`.

    Returns (chunks, search_query). `search_query` is the rewritten
    standalone query when there was prior conversation, otherwise the raw
    message — returned so the caller can log it and so a test can assert the
    rewrite actually happened.

    `history` is [(role, content)] oldest-first.

    Takes no session and opens two of its own. An AsyncSession is NOT safe
    for concurrent use, so sharing one would force the vector and text
    searches to run one after the other — and they are independent queries
    whose only real cost is a network round trip to the database. Running
    them together removes a whole round trip from the latency before the
    first token appears, which is the single most noticeable delay in the
    whole feature.
    """
    search_query = message
    if history:
        # THE step that makes follow-ups work. "what about termination?"
        # retrieves nothing useful on its own; the conversation is what
        # makes it mean "termination clause in this agreement", and only
        # the rewritten form carries that into retrieval. The chat history
        # replayed to the model is NOT enough — by then the wrong chunks
        # have already been fetched.
        rewritten = await rewrite_followup_query(history=history, message=message)
        if rewritten:
            search_query = rewritten
            logger.info("retrieval: rewrote %r -> %r", message, rewritten)

    async def vector_search() -> list[DocumentChunk]:
        async with async_session_maker() as db:
            return await _vector_candidates(
                db, document_id, search_query, settings.RETRIEVAL_CANDIDATES
            )

    async def text_search() -> list[DocumentChunk]:
        async with async_session_maker() as db:
            return await _text_candidates(
                db, document_id, search_query, settings.RETRIEVAL_CANDIDATES
            )

    vector_hits, text_hits = await asyncio.gather(vector_search(), text_search())

    chunks = _fuse(vector_hits, text_hits, settings.RETRIEVAL_TOP_K)
    logger.info(
        "retrieval: document=%s vector=%d text=%d fused=%d",
        document_id,
        len(vector_hits),
        len(text_hits),
        len(chunks),
    )
    return chunks, search_query


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Render chunks into the excerpt block the chat prompt expects.

    The page marker precedes each excerpt so the model can cite it without
    having to infer which text came from where — the single most common
    cause of a citation pointing at the wrong page.
    """
    return "\n\n".join(
        f"--- EXCERPT {index} {chunk.citation} ---\n{chunk.content}"
        for index, chunk in enumerate(chunks, start=1)
    )
