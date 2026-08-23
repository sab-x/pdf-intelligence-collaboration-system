"""The ingestion background task — PROJECT_PLAN.md §5.

Runs after POST /documents has already returned 201 with status='processing'.
Two rules this file exists to enforce:

  * It opens its OWN DB session. FastAPI tears down yield-dependencies
    before background tasks run, so a Depends()-injected session is already
    closed by the time we get here.
  * Nothing escapes. Any unhandled exception would leave the document stuck
    in 'processing' forever with the frontend polling until it gives up, so
    the whole run is wrapped and any failure is written back as
    status='failed' with a message a human can act on.

Chunking and embeddings (§5 steps e-g) degrade rather than fail: if Gemini
can't be reached, the chunks are still written (searchable by full text) and
the document still reaches 'ready'. Only the vector half of retrieval is
lost, and it can be repaired by re-uploading. Failing an entire document
because one API call timed out would discard a good summary too.
"""
import logging
import uuid

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.ai import summarize_document
from app.services.chunking import chunk_pages
from app.services.embeddings import embed_chunks
from app.services.pdf import extract_pages
from app.services.storage import download_pdf

logger = logging.getLogger(__name__)

# Below this, the PDF has no meaningful selectable text — almost always a
# scan. §5 step c: fail loudly with a human message rather than silently
# succeeding with an empty summary.
MIN_EXTRACTED_CHARS = 100

SCANNED_PDF_MESSAGE = (
    "This PDF appears to be a scanned image with no selectable text. "
    "Text extraction and AI features are unavailable for it."
)
GENERIC_FAILURE_MESSAGE = (
    "We couldn't process this PDF. Please try uploading it again, or upload a different file."
)


async def ingest(document_id: uuid.UUID) -> None:
    """Entry point queued via BackgroundTasks. Never raises."""
    try:
        await _run(document_id)
    except Exception:
        # Broad by design: a background task has no caller to handle this,
        # and any escape leaves the document wedged in 'processing'.
        logger.exception("ingestion failed for document %s", document_id)
        await _mark_failed(document_id, GENERIC_FAILURE_MESSAGE)


async def _run(document_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        document = await db.get(Document, document_id)
        if document is None:
            # Deleted between upload and ingestion — nothing to do, and
            # nothing to report as a failure.
            logger.warning("ingest: document %s no longer exists", document_id)
            return

        logger.info("ingest: starting %s (%s)", document_id, document.filename)

        # a. Download bytes  (supabase-py is synchronous; storage.py hops
        #    to a thread for us)
        pdf_bytes = await download_pdf(document.storage_key)

        # b. Extract per-page text. PyMuPDF is CPU-bound C code — off the
        #    event loop or it freezes health checks and status polling.
        pages = await run_in_threadpool(extract_pages, pdf_bytes)
        extracted_chars = sum(len(page) for page in pages)

        document.page_count = len(pages)
        document.extracted_chars = extracted_chars

        # c. Scanned-PDF case
        if extracted_chars < MIN_EXTRACTED_CHARS:
            logger.info(
                "ingest: %s has only %d extracted chars — treating as scanned",
                document_id,
                extracted_chars,
            )
            document.status = "failed"
            document.error_message = SCANNED_PDF_MESSAGE
            await db.commit()
            return

        # d. Summarise (§6). summarize_document never raises; a degraded
        #    result still yields a readable document.
        summary = await summarize_document(
            filename=document.filename,
            page_count=len(pages),
            text="\n\n".join(pages),
        )
        if summary.degraded:
            logger.warning("ingest: %s completed with a degraded summary", document_id)

        document.summary = summary.summary
        document.doc_type = summary.doc_type
        document.key_points = summary.key_points

        # e-g. Chunk, embed, index. Never fatal — see the module docstring.
        embedded_count = await _index_chunks(db, document, pages, summary_degraded=summary.degraded)

        # h. Ready.
        document.status = "ready"
        document.error_message = None
        await db.commit()

        logger.info(
            "ingest: %s ready (%d pages, %d chars, %d embedded chunks)",
            document_id,
            len(pages),
            extracted_chars,
            embedded_count,
        )


async def _index_chunks(
    db: AsyncSession,
    document: Document,
    pages: list[str],
    *,
    summary_degraded: bool,
) -> int:
    """Chunk the document, embed the chunks, and store both. Returns the
    number of chunks that got a vector.

    Never raises: every failure path here leaves the document usable.
    """
    # Idempotent re-ingest. Without this, uploading the same document twice
    # would collide on uq_document_chunks_document_id_chunk_index, and a
    # partial rewrite would leave stale chunks that retrieval would happily
    # return alongside the new ones.
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))

    chunks = chunk_pages(
        pages,
        target_tokens=settings.CHUNK_TARGET_TOKENS,
        overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
    )
    if not chunks:
        logger.warning("ingest: %s produced no chunks", document.id)
        return 0

    vectors = await embed_chunks([chunk.content for chunk in chunks])

    embedded_count = 0
    for chunk, vector in zip(chunks, vectors, strict=True):
        # strict=True is load-bearing: embed_chunks promises positional
        # alignment, and a length mismatch would attach chunk N's vector to
        # chunk N+1 — wrong answers with confident citations, the worst
        # possible failure mode for this feature. Fail loudly instead.
        if vector is not None:
            embedded_count += 1
        db.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                token_estimate=chunk.token_estimate,
                embedding=vector,
            )
        )

    if embedded_count < len(chunks):
        logger.warning(
            "ingest: %s embedded %d/%d chunks — vector retrieval will be partial, "
            "full-text still covers the rest",
            document.id,
            embedded_count,
            len(chunks),
        )

    # g. Summary embedding, for semantic dashboard search (§8).
    #
    # embed_chunks, NOT embed_query: the summary is indexed content that
    # search queries are compared AGAINST, so it must use the same
    # RETRIEVAL_DOCUMENT projection as the chunks. Embedding it as a query
    # would put it in the wrong half of the model's asymmetric space and
    # quietly cost recall on every semantic search.
    #
    # Skipped when the summary is the degraded fallback text: embedding
    # "We couldn't summarise this document" would make it a weak match for
    # unrelated queries.
    if not summary_degraded and document.summary:
        summary_vectors = await embed_chunks([document.summary])
        document.summary_embedding = summary_vectors[0] if summary_vectors else None

    return embedded_count


async def _mark_failed(document_id: uuid.UUID, message: str) -> None:
    """Record the failure on a FRESH session — whatever went wrong may have
    left the original session in an unusable state (a DB error rolls the
    transaction back), and this write is the only thing stopping the
    frontend from polling a dead document for five minutes.
    """
    try:
        async with async_session_maker() as db:
            document = await db.get(Document, document_id)
            if document is None:
                return
            document.status = "failed"
            document.error_message = message
            await db.commit()
    except Exception:
        logger.exception("could not mark document %s as failed", document_id)
