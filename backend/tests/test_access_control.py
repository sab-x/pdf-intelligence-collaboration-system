"""Access control — the five cases in PROJECT_PLAN.md §11, plus one more.

These are the tests that matter most in this suite. Everything else here
checks that a feature works; these check that a feature can't be abused,
and every one of them corresponds to a way the app could leak someone
else's document.

## On 404 vs 403

Phase 3's rule — never confirm a document exists to a stranger — still
holds exactly as written. Phase 8 added a case it didn't have: a caller
holding a live link to this document but not enough permission on it.

    granted == NONE            -> 404   stranger, guest token for another
                                        document, revoked link, expired link
    NONE < granted < minimum   -> 403   known party, insufficient permission

The extra test beyond §11's five is test_403_is_never_an_existence_oracle,
which pins the property the split depends on: reaching a 403 at all
requires access the caller demonstrably already has. Without it, someone
could later "simplify" the two branches into one and turn 403 into a probe
for which document ids are real.
"""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

REAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _stub_storage_and_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch Supabase or Gemini. Patched where they're used, per the
    standard rule, matching test_upload.py.
    """

    async def _fake_upload(_key: str, _content: bytes) -> None:
        return None

    async def _fake_ingest(_document_id: object) -> None:
        return None

    monkeypatch.setattr("app.api.v1.documents.upload_pdf", _fake_upload)
    monkeypatch.setattr("app.api.v1.documents.ingest", _fake_ingest)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(client: AsyncClient, name: str = "Owner") -> str:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload(client: AsyncClient, token: str, filename: str = "doc.pdf") -> str:
    resp = await client.post(
        "/api/v1/documents",
        headers=_auth(token),
        files={"file": (filename, REAL_PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_share(
    client: AsyncClient, token: str, document_id: str, permission: str = "comment"
) -> dict:
    resp = await client.post(
        f"/api/v1/documents/{document_id}/shares",
        headers=_auth(token),
        json={"permission": permission},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _guest_token(client: AsyncClient, share_token: str, name: str = "Guest") -> str:
    resp = await client.post(
        f"/api/v1/share/{share_token}/session",
        json={"display_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["guest_token"]


# ---------------------------------------------------------------------------
# §11 case 1 — cross-user document access
# ---------------------------------------------------------------------------


async def test_user_b_cannot_read_user_as_document(client: AsyncClient) -> None:
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)

    other = await _signup(client, "Other")
    resp = await client.get(f"/api/v1/documents/{document_id}", headers=_auth(other))

    # 404, not 403: a stranger must not learn this id corresponds to a
    # real document.
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# §11 case 2 — a guest token is scoped to exactly one document
# ---------------------------------------------------------------------------


async def test_guest_token_for_one_document_cannot_reach_another(
    client: AsyncClient,
) -> None:
    owner = await _signup(client, "Owner")
    shared_id = await _upload(client, owner, "shared.pdf")
    private_id = await _upload(client, owner, "private.pdf")

    share = await _create_share(client, owner, shared_id)
    guest = await _guest_token(client, share["token"])

    # The token it was issued for: fine.
    allowed = await client.get(f"/api/v1/documents/{shared_id}", headers=_auth(guest))
    assert allowed.status_code == 200, allowed.text

    # A different document owned by the same user: invisible. This is the
    # check that makes a share link a share of ONE document rather than of
    # the owner's whole library.
    denied = await client.get(f"/api/v1/documents/{private_id}", headers=_auth(guest))
    assert denied.status_code == 404, denied.text


# ---------------------------------------------------------------------------
# §11 case 3 — revocation takes effect immediately
# ---------------------------------------------------------------------------


async def test_revoked_share_link_stops_working(client: AsyncClient) -> None:
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)
    share = await _create_share(client, owner, document_id)
    guest = await _guest_token(client, share["token"])

    before = await client.get(f"/api/v1/documents/{document_id}", headers=_auth(guest))
    assert before.status_code == 200

    revoke = await client.delete(f"/api/v1/shares/{share['id']}", headers=_auth(owner))
    assert revoke.status_code == 204

    # The guest JWT is still cryptographically valid and unexpired — this
    # passing is what proves authorization is re-derived from the database
    # on every request rather than trusted from the token.
    after = await client.get(f"/api/v1/documents/{document_id}", headers=_auth(guest))
    assert after.status_code == 404, after.text

    # And the public link itself is dead, so nobody can mint a new session.
    preview = await client.get(f"/api/v1/share/{share['token']}")
    assert preview.status_code == 404, preview.text


async def test_revoking_a_share_link_is_idempotent(client: AsyncClient) -> None:
    """Revoking twice is the caller's intent already satisfied, not an error."""
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)
    share = await _create_share(client, owner, document_id)

    first = await client.delete(f"/api/v1/shares/{share['id']}", headers=_auth(owner))
    second = await client.delete(f"/api/v1/shares/{share['id']}", headers=_auth(owner))

    assert first.status_code == 204
    assert second.status_code == 204


# ---------------------------------------------------------------------------
# §11 case 4 — permission ladder within a valid link
# ---------------------------------------------------------------------------


async def test_view_only_guest_cannot_comment(client: AsyncClient) -> None:
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)
    share = await _create_share(client, owner, document_id, permission="view")
    guest = await _guest_token(client, share["token"])

    # Reading is what they were granted.
    read = await client.get(f"/api/v1/documents/{document_id}", headers=_auth(guest))
    assert read.status_code == 200

    # Commenting is not. 403 rather than 404: they are already looking at
    # this document through a live link, so hiding its existence would
    # protect nothing and only confuse them.
    write = await client.post(
        f"/api/v1/documents/{document_id}/comments",
        headers=_auth(guest),
        json={"body_markdown": "I should not be able to post this."},
    )
    assert write.status_code == 403, write.text


async def test_comment_permission_guest_can_comment(client: AsyncClient) -> None:
    """The positive case, so the 403 above is proven to be about permission
    and not about guests being unable to comment at all.
    """
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)
    share = await _create_share(client, owner, document_id, permission="comment")
    guest = await _guest_token(client, share["token"], name="Priya")

    resp = await client.post(
        f"/api/v1/documents/{document_id}/comments",
        headers=_auth(guest),
        json={"body_markdown": "Reading this now."},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["author_label"] == "Priya"
    # A guest is not the owner, whatever else is true of them.
    assert body["is_document_owner"] is False


# ---------------------------------------------------------------------------
# The extra one — 403 must never become an existence oracle
# ---------------------------------------------------------------------------


async def test_403_is_never_an_existence_oracle(client: AsyncClient) -> None:
    """Every way of NOT holding a live link to a document yields 404.

    403 is reachable only with a live, unrevoked, unexpired, document-matching
    link — i.e. only by someone who already knows the document exists. If any
    of these started returning 403, an attacker could distinguish real
    document ids from invented ones by watching the status code.

    Uses a COMMENT-permission route as the probe, because that's the route
    where the 403 branch actually exists.
    """
    owner = await _signup(client, "Owner")
    shared_id = await _upload(client, owner, "shared.pdf")
    other_id = await _upload(client, owner, "other.pdf")
    share = await _create_share(client, owner, shared_id, permission="view")
    guest = await _guest_token(client, share["token"])
    stranger = await _signup(client, "Stranger")

    comment_body = {"body_markdown": "probe"}

    # a. A signed-in user with no relationship to the document.
    resp = await client.post(
        f"/api/v1/documents/{shared_id}/comments",
        headers=_auth(stranger),
        json=comment_body,
    )
    assert resp.status_code == 404, f"stranger got {resp.status_code}, expected 404"

    # b. A guest whose link points at a different document.
    resp = await client.post(
        f"/api/v1/documents/{other_id}/comments",
        headers=_auth(guest),
        json=comment_body,
    )
    assert resp.status_code == 404, f"wrong-doc guest got {resp.status_code}, expected 404"

    # c. A document id that doesn't exist at all.
    resp = await client.post(
        f"/api/v1/documents/{uuid.uuid4()}/comments",
        headers=_auth(stranger),
        json=comment_body,
    )
    assert resp.status_code == 404, f"nonexistent doc got {resp.status_code}, expected 404"

    # d. A guest whose link has been revoked.
    await client.delete(f"/api/v1/shares/{share['id']}", headers=_auth(owner))
    resp = await client.post(
        f"/api/v1/documents/{shared_id}/comments",
        headers=_auth(guest),
        json=comment_body,
    )
    assert resp.status_code == 404, f"revoked guest got {resp.status_code}, expected 404"


async def test_guest_cannot_create_a_share_link(client: AsyncClient) -> None:
    """Sharing is an owner action. A guest re-sharing a document they were
    shown would let a link outlive its own revocation.
    """
    owner = await _signup(client, "Owner")
    document_id = await _upload(client, owner)
    share = await _create_share(client, owner, document_id)
    guest = await _guest_token(client, share["token"])

    resp = await client.post(
        f"/api/v1/documents/{document_id}/shares",
        headers=_auth(guest),
        json={"permission": "comment"},
    )

    # 403: they hold a live link to this document, just not owner rights.
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# §11 case 5 — deferred to Phase 10
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="chat_sessions lands in Phase 10 (RAG chat); unskip with the chat routes"
)
async def test_guest_cannot_read_the_owners_chat_session(client: AsyncClient) -> None:
    """A guest holding a share link must not read the owner's chat history
    by supplying the owner's session_id.

    require_document_access only decides DOCUMENT access — both chat routes
    additionally have to verify that the supplied session_id belongs to the
    calling principal (chat_sessions.user_id or .guest_session_id). Without
    that second check this is a real hole, not a theoretical one.

    Import ChatSession INSIDE the body, not at module level: the model
    doesn't exist yet, and a module-level import would fail at collection
    time — before the skip mark ever applies — and take the whole file with
    it.
    """
    from app.models.chat import ChatSession  # noqa: F401

    raise AssertionError("unimplemented — see Phase 10")
