"""Sharing + guest sessions — PROJECT_PLAN.md §3, §4.

Five routes across two trust levels, which is why they share a router but
not a prefix:

  authenticated, owner-only
    POST   /documents/{document_id}/shares
    GET    /documents/{document_id}/shares
    DELETE /shares/{share_id}

  public, no credentials at all
    GET    /share/{token}
    POST   /share/{token}/session

The two owner routes carrying {document_id} go through
require_document_access(Access.OWNER) like everything else. DELETE
/shares/{share_id} cannot — it's addressed by share id, so there is no
{document_id} in the path for that dependency to bind. It follows the exact
precedent set by DELETE /comments/{comment_id}: load the parent document,
check ownership, and answer every refusal with 404 so nobody learns a share
link exists that isn't theirs.

Revocation is a soft delete. `revoked_at` is set and the row stays, which
keeps guest sessions (and therefore guest comments) intact and permanently
burns the token rather than freeing it for reuse.
"""
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Access, Principal, require_document_access, require_user
from app.core.limiter import limiter
from app.core.security import create_guest_token
from app.db.session import get_db
from app.models.document import Document
from app.models.guest_session import GuestSession
from app.models.share_link import ShareLink
from app.models.user import User
from app.schemas.share import (
    GuestSessionCreateRequest,
    GuestSessionResponse,
    ShareLinkCreateRequest,
    ShareLinkResponse,
    SharePreviewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sharing"])

#: 32 bytes -> 256 bits of entropy, ~43 URL-safe characters. Unguessable is
#: the entire security model of a public link, so this is not negotiable
#: down to something prettier.
SHARE_TOKEN_BYTES = 32


def _share_url(token: str) -> str:
    """Build the link the owner copies.

    Uses FRONTEND_URL, not BACKEND_URL — the share page is a React route.
    rstrip guards against a trailing slash in the env var producing a
    double slash that some proxies normalise and others don't.
    """
    return f"{settings.FRONTEND_URL.rstrip('/')}/share/{token}"


def _to_response(link: ShareLink, *, now: datetime | None = None) -> ShareLinkResponse:
    now = now or datetime.now(timezone.utc)
    return ShareLinkResponse(
        id=link.id,
        token=link.token,
        url=_share_url(link.token),
        permission=link.permission,  # type: ignore[arg-type]
        invited_email=link.invited_email,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        last_accessed_at=link.last_accessed_at,
        view_count=link.view_count,
        created_at=link.created_at,
        is_active=link.is_live(now=now),
    )


async def _load_live_link(token: str, db: AsyncSession) -> ShareLink:
    """Resolve a public token to a usable link, or 404.

    Revoked, expired and never-existed all produce the same 404 with the
    same message. Distinguishing them would turn this endpoint into an
    oracle telling an attacker which guessed tokens were once real.
    """
    link = await db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None or not link.is_live(now=datetime.now(timezone.utc)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is no longer valid")
    return link


# ---------------------------------------------------------------------------
# Owner routes
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/shares",
    response_model=ShareLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_share_link(
    body: ShareLinkCreateRequest,
    access: tuple[Document, Access] = Depends(require_document_access(Access.OWNER)),
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ShareLinkResponse:
    document, _granted = access

    expires_at: datetime | None = None
    if body.expires_in_hours is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)

    link = ShareLink(
        document_id=document.id,
        created_by=principal.user_id,
        token=secrets.token_urlsafe(SHARE_TOKEN_BYTES),
        permission=body.permission,
        invited_email=body.invited_email,
        expires_at=expires_at,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    # The token itself is never logged — it is the credential.
    logger.info(
        "share link created: document=%s link=%s permission=%s",
        document.id,
        link.id,
        link.permission,
    )
    return _to_response(link)


@router.get(
    "/documents/{document_id}/shares",
    response_model=list[ShareLinkResponse],
)
async def list_share_links(
    access: tuple[Document, Access] = Depends(require_document_access(Access.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> list[ShareLinkResponse]:
    """Every link on this document, newest first — revoked ones included.

    Revoked links are returned rather than filtered out so the owner can see
    what they've already turned off instead of wondering whether a link they
    remember creating ever existed. `is_active` is what the UI renders on.
    """
    document, _granted = access

    result = await db.execute(
        select(ShareLink)
        .where(ShareLink.document_id == document.id)
        .order_by(ShareLink.created_at.desc())
    )
    now = datetime.now(timezone.utc)
    return [_to_response(link, now=now) for link in result.scalars().all()]


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    share_id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft revoke. Owner of the parent document only.

    Cannot use require_document_access — addressed by share id, so there is
    no {document_id} in the path to bind. Same shape as DELETE
    /comments/{comment_id}: every refusal is 404.

    Idempotent. Revoking an already-revoked link is a no-op returning 204,
    not a 409 — the caller's intent ("this link should not work") is already
    satisfied, and an error would just make the UI handle a state that isn't
    a problem.
    """
    link = await db.get(ShareLink, share_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share link not found")

    document = await db.get(Document, link.document_id)
    if document is None or document.owner_id != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share link not found")

    if link.revoked_at is None:
        link.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("share link revoked: document=%s link=%s", document.id, link.id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Public routes — no Authorization header, no principal
# ---------------------------------------------------------------------------


@router.get("/share/{token}", response_model=SharePreviewResponse)
async def preview_share(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> SharePreviewResponse:
    """What an anonymous visitor sees before entering a display name.

    Deliberately does NOT return the document id or the AI summary — see
    schemas/share.py. Bumps view_count so the owner can tell a link has been
    opened even if the visitor never identifies themselves.
    """
    link = await _load_live_link(token, db)

    document = await db.get(Document, link.document_id)
    if document is None:
        # The document was deleted but the cascade left this reachable
        # somehow. Same 404 as an invalid token.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is no longer valid")

    owner = await db.get(User, document.owner_id)

    link.view_count += 1
    link.last_accessed_at = datetime.now(timezone.utc)
    await db.commit()

    return SharePreviewResponse(
        filename=document.filename,
        page_count=document.page_count,
        permission=link.permission,  # type: ignore[arg-type]
        shared_by=owner.name if owner is not None else "Someone",
    )


@router.post(
    "/share/{token}/session",
    response_model=GuestSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def create_guest_session(
    request: Request,
    token: str,
    body: GuestSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> GuestSessionResponse:
    """Exchange a display name for a document-scoped guest JWT.

    Rate limited on the same budget as login/signup: this mints credentials
    from an unauthenticated request, so it belongs in that bucket rather
    than being left open.

    A fresh guest_sessions row per submission, deliberately — two people
    opening the same link are two identities with two names, and their
    comments must not merge into one author.
    """
    link = await _load_live_link(token, db)

    guest_session = GuestSession(
        share_link_id=link.id,
        display_name=body.display_name,
    )
    db.add(guest_session)
    await db.commit()
    await db.refresh(guest_session)

    guest_token = create_guest_token(
        guest_session_id=guest_session.id,
        share_link_id=link.id,
        document_id=link.document_id,
    )

    logger.info(
        "guest session created: document=%s link=%s guest=%s",
        link.document_id,
        link.id,
        guest_session.id,
    )

    return GuestSessionResponse(
        guest_token=guest_token,
        expires_in_seconds=settings.GUEST_TOKEN_HOURS * 3600,
        document_id=link.document_id,
        permission=link.permission,  # type: ignore[arg-type]
        display_name=guest_session.display_name,
    )
