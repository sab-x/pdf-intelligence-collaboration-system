"""Principal + document-access authorization — PROJECT_PLAN.md §4.

One concept: the Principal. Every document/comment/chat route depends on
require_document_access() — it is the ONLY place document permission is
decided.

Phase 3 built the owner branch. Phase 8 adds the guest branch: a share-link
JWT resolves to kind="guest", and access is re-derived from the database on
every request rather than trusted from the token.

## On 404 vs 403

Phase 3's rule was "never 403" — don't confirm a document exists to
strangers. That rule stands exactly as written. What Phase 8 adds is a case
Phase 3 didn't have: a caller who legitimately holds access to this
document but not *enough* of it.

    granted == NONE            -> 404   stranger, guest token for another
                                        document, revoked link, expired link
    NONE < granted < minimum   -> 403   known party, insufficient permission

A view-permission guest attempting to comment is already looking at the
document through a valid link. Hiding it from them protects no information
and just lies. Crucially, 403 can never become an existence oracle: every
way of failing to hold a live, unrevoked, unexpired, document-matching link
produces granted == NONE and therefore 404, so reaching the 403 branch at
all requires access the caller demonstrably already has. test_access_control
asserts that property directly.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.document import Document
from app.models.guest_session import GuestSession
from app.models.share_link import ShareLink

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    kind: Literal["user", "guest"]
    user_id: UUID | None
    guest_session_id: UUID | None
    share_link_id: UUID | None
    display_name: str


class Access(str, Enum):
    NONE = "none"
    VIEW = "view"
    COMMENT = "comment"
    OWNER = "owner"


_ACCESS_RANK: dict[Access, int] = {
    Access.NONE: 0,
    Access.VIEW: 1,
    Access.COMMENT: 2,
    Access.OWNER: 3,
}


async def resolve_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Decode the caller's identity from the Authorization header.

    Tries a user access token first, then a guest token. decode_token
    enforces the `kind` claim on each attempt, so there is no path by which a
    guest JWT resolves to kind="user" — the two are distinguished by a signed
    claim, not by shape.

    The guest branch reads guest_sessions to recover display_name. That row
    also has to still exist: if it's gone, the guest's identity is gone with
    it and the token is treated as invalid rather than resolving to an
    anonymous principal with a blank label.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    raw = credentials.credentials

    try:
        payload = decode_token(raw, expected_kind="access")
    except TokenError:
        pass
    else:
        return Principal(
            kind="user",
            user_id=UUID(payload["sub"]),
            guest_session_id=None,
            share_link_id=None,
            display_name="",
        )

    try:
        payload = decode_token(raw, expected_kind="guest")
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token"
        ) from exc

    try:
        guest_session_id = UUID(payload["sid"])
        share_link_id = UUID(payload["slid"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token"
        ) from exc

    guest_session = await db.get(GuestSession, guest_session_id)
    if guest_session is None or guest_session.share_link_id != share_link_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    return Principal(
        kind="guest",
        user_id=None,
        guest_session_id=guest_session_id,
        share_link_id=share_link_id,
        display_name=guest_session.display_name,
    )


async def require_user(principal: Principal = Depends(resolve_principal)) -> Principal:
    """Guard for routes a guest must never reach — uploading, sharing, deleting.

    Now that guest tokens actually resolve, this stopped being a formality.
    Anything that creates or administers a document depends on this, so a
    guest token presented to it is rejected as unauthenticated rather than
    falling through to a document-level check that was never designed to
    answer the question.
    """
    if principal.kind != "user" or principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return principal


async def resolve_access(
    document: Document, principal: Principal, db: AsyncSession
) -> Access:
    """Derive what this principal may do with this document.

    Returns Access.NONE for anything that isn't a positive grant. It never
    raises, so callers own the status code — require_document_access turns
    NONE into 404, and routes addressed by a child id (DELETE
    /comments/{id}, DELETE /shares/{id}) call this directly rather than
    re-deriving the rule, which is how those routes stay honest about
    revoked links without a second copy of the logic.
    """
    if principal.kind == "user" and principal.user_id == document.owner_id:
        return Access.OWNER

    if principal.kind == "guest" and principal.share_link_id is not None:
        link = await db.get(ShareLink, principal.share_link_id)
        if link is None:
            return Access.NONE
        # Re-read from the database, never trust the token's `doc` claim: a
        # link revoked after the token was minted must stop working now, not
        # in 24 hours.
        if not link.is_live(now=datetime.now(timezone.utc)):
            return Access.NONE
        if link.document_id != document.id:
            return Access.NONE
        return Access(link.permission)

    return Access.NONE


def require_document_access(minimum: Access):
    """Returns a FastAPI dependency enforcing `minimum` access on the
    document identified by the route's {document_id} path parameter.

    This has to be a factory rather than a flat dependency function because
    `minimum` is fixed per call site, not part of the request — FastAPI
    resolves a dependency's other parameters (document_id, principal, db) by
    name against the request regardless, so `document_id` is still bound
    correctly from the path even though the route handler never declares it.
    """

    async def _dependency(
        document_id: UUID,
        principal: Principal = Depends(resolve_principal),
        db: AsyncSession = Depends(get_db),
    ) -> tuple[Document, Access]:
        document = await db.get(Document, document_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

        granted = await resolve_access(document, principal, db)

        if granted == Access.NONE:
            # No relationship to this document at all. Never confirm it exists.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

        if _ACCESS_RANK[granted] < _ACCESS_RANK[minimum]:
            # Holds a live link to this exact document, just not enough
            # permission. They already know it exists; 404 here would be a
            # lie that helps nobody. See the module docstring.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You don't have permission to do that on this document",
            )

        return document, granted

    return _dependency
