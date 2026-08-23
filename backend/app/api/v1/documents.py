"""Document upload + status + signed-URL routes — PROJECT_PLAN.md §3, §5.

Upload validates, stores the blob, inserts the row as status='processing'
and queues ingest() — then returns 201 immediately. Extraction and
summarisation happen afterwards in the background task; the frontend polls
/status until it flips to 'ready' or 'failed'.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Access, Principal, require_document_access, require_user
from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import (
    DocumentResponse,
    DocumentStatusResponse,
    SignedUrlResponse,
)
from app.services.storage import (
    build_storage_key,
    create_signed_url,
    delete_pdf,
    upload_pdf,
)
from app.workers.ingest import ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

PDF_MAGIC_BYTES = b"%PDF-"
_UPLOAD_CHUNK_SIZE = 1024 * 1024


def _sanitize_filename(raw: str | None) -> str:
    """For DISPLAY only — never used to build the storage path. Strips any
    path component regardless of which separator the client's OS used.
    """
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    return name or "document.pdf"


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Reads the upload in chunks, aborting as soon as the size cap is
    exceeded, instead of buffering an arbitrarily large body into memory
    first and rejecting only after the fact.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    filename = _sanitize_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .pdf files are accepted.")
    if file.content_type != "application/pdf":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Type must be application/pdf.")

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    content = await _read_bounded(file, max_bytes)

    if not content.startswith(PDF_MAGIC_BYTES):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This file doesn't look like a real PDF (magic bytes check failed).",
        )

    # principal.user_id is guaranteed non-None here — require_user() rejects
    # anything else before this handler runs.
    assert principal.user_id is not None
    document_id = uuid.uuid4()
    storage_key = build_storage_key(principal.user_id, document_id)
    await upload_pdf(storage_key, content)

    document = Document(
        id=document_id,
        owner_id=principal.user_id,
        filename=filename,
        storage_key=storage_key,
        size_bytes=len(content),
        status="processing",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # BackgroundTasks, not asyncio.create_task: Starlette runs this after the
    # response is sent and keeps a reference to it, so it can't be garbage
    # collected mid-flight the way a bare create_task can. ingest() opens its
    # own DB session — the one above is closed before this runs.
    background_tasks.add_task(ingest, document.id)

    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    """The caller's own documents, newest first (PROJECT_PLAN.md §3).

    Scoped to owner_id in the WHERE clause — this is the one document route
    that isn't addressed by id, so require_document_access has nothing to
    check and the ownership filter IS the authorization. No search params:
    §3 keeps all searching on /search so it's built once.
    """
    result = await db.execute(
        select(Document)
        .where(Document.owner_id == principal.user_id)
        .order_by(Document.created_at.desc())
    )
    return [DocumentResponse.model_validate(doc) for doc in result.scalars().all()]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    access: tuple[Document, Access] = Depends(require_document_access(Access.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Owner-only. Removes the blob and the row.

    Blob first, then the row: if the blob delete fails we still drop the row
    rather than leaving the user staring at a document they cannot delete.
    That trades a possible orphaned object in the bucket for a UI that never
    gets stuck — the orphan is invisible and reclaimable, the stuck row is
    neither. The failure is logged loudly so it can be swept later.

    FastAPI caches dependencies per request, so `db` here is the very same
    session require_document_access already used to load the document.
    """
    document, _granted = access
    storage_key = document.storage_key

    try:
        await delete_pdf(storage_key)
    except Exception:
        logger.exception(
            "storage delete failed for document %s (key=%s); deleting the row anyway "
            "- this blob is now orphaned in the bucket",
            document.id,
            storage_key,
        )

    await db.delete(document)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
) -> DocumentResponse:
    """Metadata + summary (PROJECT_PLAN.md §3). This is what the frontend
    fetches once /status reports 'ready'.

    DocumentResponse is the same DTO POST returns, so storage_key stays
    server-side; the authz check is require_document_access, never an
    owner_id comparison inlined here.
    """
    document, _granted = access
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
) -> DocumentStatusResponse:
    """Polled every 2s by the frontend while a document is processing, so it
    stays deliberately small — no summary, no key points.
    """
    document, _granted = access
    return DocumentStatusResponse.model_validate(document)


@router.get("/{document_id}/file", response_model=SignedUrlResponse)
async def get_document_file_url(
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
) -> SignedUrlResponse:
    document, _granted = access
    url = await create_signed_url(document.storage_key, settings.SIGNED_URL_TTL_SECONDS)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.SIGNED_URL_TTL_SECONDS)
    return SignedUrlResponse(url=url, expires_at=expires_at)
