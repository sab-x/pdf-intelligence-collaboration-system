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

Chunking, embeddings, and summary_embedding (§5 steps e-g) are Phase 9.
"""
import logging
import uuid

from fastapi.concurrency import run_in_threadpool

from app.db.session import async_session_maker
from app.models.document import Document
from app.services.ai import summarize_document
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

        # h. Ready. (e-g — chunk, embed, embed summary — arrive in Phase 9.)
        document.status = "ready"
        document.error_message = None
        await db.commit()

        logger.info(
            "ingest: %s ready (%d pages, %d chars)",
            document_id,
            len(pages),
            extracted_chars,
        )


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
