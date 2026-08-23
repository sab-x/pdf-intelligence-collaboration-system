"""Upload validation tests — magic-byte rejection, the size cap, and the
happy path. Supabase Storage is mocked (monkeypatched where
app/api/v1/documents.py calls it, per the standard "patch where it's used"
rule) — these tests never touch a real bucket.
"""
import io

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# A minimal but structurally real PDF — starts with the %PDF- magic bytes.
REAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


async def _signup_and_get_token(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"name": "Uploader", "email": email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _upload_pdf_should_not_be_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("upload_pdf should not be called when validation fails")


@pytest.fixture(autouse=True)
def _stub_ingest(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """POST /documents now queues ingest() as a BackgroundTask, and the ASGI
    test transport really does run background tasks after the response — so
    without this stub the happy-path test would hit Supabase and Gemini for
    real. Records the queued document ids instead.
    """
    queued: list[object] = []

    async def _fake_ingest(document_id: object) -> None:
        queued.append(document_id)

    monkeypatch.setattr("app.api.v1.documents.ingest", _fake_ingest)
    return queued


async def test_non_pdf_renamed_to_pdf_is_rejected(
    client: AsyncClient, unique_email: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.documents.upload_pdf", _upload_pdf_should_not_be_called)
    token = await _signup_and_get_token(client, unique_email)

    files = {
        "file": (
            "contract.pdf",
            io.BytesIO(b"This is just a plain text file, not a real PDF."),
            "application/pdf",
        )
    }
    resp = await client.post(
        "/api/v1/documents", files=files, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 400, resp.text
    assert "magic bytes" in resp.json()["detail"].lower()


async def test_oversized_file_is_rejected(
    client: AsyncClient, unique_email: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings as app_settings

    monkeypatch.setattr("app.api.v1.documents.upload_pdf", _upload_pdf_should_not_be_called)
    # Drop the cap to 0 MB so any non-empty body exceeds it immediately —
    # avoids actually shipping tens of MB over the wire in a test.
    monkeypatch.setattr(app_settings, "MAX_UPLOAD_MB", 0)
    token = await _signup_and_get_token(client, unique_email)

    files = {"file": ("contract.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")}
    resp = await client.post(
        "/api/v1/documents", files=files, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 413, resp.text


async def test_valid_pdf_upload_returns_201_processing(
    client: AsyncClient,
    unique_email: str,
    monkeypatch: pytest.MonkeyPatch,
    _stub_ingest: list[object],
) -> None:
    uploaded: dict[str, object] = {}

    async def _fake_upload_pdf(storage_key: str, content: bytes) -> None:
        uploaded["storage_key"] = storage_key
        uploaded["content"] = content

    monkeypatch.setattr("app.api.v1.documents.upload_pdf", _fake_upload_pdf)
    token = await _signup_and_get_token(client, unique_email)

    files = {"file": ("Contract v2.pdf", io.BytesIO(REAL_PDF_BYTES), "application/pdf")}
    resp = await client.post(
        "/api/v1/documents", files=files, headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "processing"
    assert body["filename"] == "Contract v2.pdf"
    assert "storage_key" not in body

    assert uploaded["content"] == REAL_PDF_BYTES
    assert str(uploaded["storage_key"]).endswith(".pdf")

    # The row is returned as 'processing' AND ingestion is actually queued
    # for it — 201 before any extraction happens (PROJECT_PLAN.md §5).
    assert [str(doc_id) for doc_id in _stub_ingest] == [body["id"]]
