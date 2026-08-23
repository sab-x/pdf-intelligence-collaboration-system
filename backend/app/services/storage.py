"""Supabase Storage helpers.

supabase-py's storage client is synchronous under the hood (plain requests
calls), so every call here runs through run_in_threadpool to avoid blocking
the event loop (PROJECT_PLAN.md §5).
"""
import uuid

from fastapi.concurrency import run_in_threadpool
from supabase import Client, create_client

from app.core.config import settings

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _client


def build_storage_key(owner_id: uuid.UUID, document_id: uuid.UUID) -> str:
    """Derived entirely from UUIDs — never from a user-supplied filename or
    path, so it can't be used for path traversal or to collide with another
    owner's object.
    """
    return f"{owner_id}/{document_id}.pdf"


async def upload_pdf(storage_key: str, content: bytes) -> None:
    client = _get_client()

    def _upload() -> None:
        client.storage.from_(settings.SUPABASE_BUCKET).upload(
            storage_key,
            content,
            file_options={"content-type": "application/pdf"},
        )

    await run_in_threadpool(_upload)


async def create_signed_url(storage_key: str, expires_in_seconds: int) -> str:
    client = _get_client()

    def _sign() -> str:
        result = client.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
            storage_key, expires_in_seconds
        )
        return result["signedURL"]

    return await run_in_threadpool(_sign)


async def download_pdf(storage_key: str) -> bytes:
    client = _get_client()

    def _download() -> bytes:
        return client.storage.from_(settings.SUPABASE_BUCKET).download(storage_key)

    return await run_in_threadpool(_download)


async def delete_pdf(storage_key: str) -> None:
    client = _get_client()

    def _delete() -> None:
        client.storage.from_(settings.SUPABASE_BUCKET).remove([storage_key])

    await run_in_threadpool(_delete)
