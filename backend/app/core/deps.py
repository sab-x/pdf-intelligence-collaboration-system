"""Principal + document-access authorization — PROJECT_PLAN.md §4.

One concept: the Principal. Every document/comment/chat route is meant to
depend on require_document_access() — it is the ONLY place document
permission is decided.

Phase 3 implements the owner-only branch. Guest JWTs (share links) are a
Phase 8 feature: resolve_principal() only decodes "access"-kind (user)
tokens for now — a guest-kind token fails the kind check inside
decode_token and is rejected as unauthenticated, which is the correct
fail-closed default until the real guest branch exists.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.document import Document

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
) -> Principal:
    """Decode the caller's identity from the Authorization header.

    Only user access tokens resolve today. A guest JWT (kind="guest", per
    §4's token design) will fail decode_token's kind check and land in the
    except branch below just like any other invalid token — there is no
    silent guest-to-user mapping.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials, expected_kind="access")
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token"
        ) from exc

    return Principal(
        kind="user",
        user_id=UUID(payload["sub"]),
        guest_session_id=None,
        share_link_id=None,
        display_name="",
    )


async def require_user(principal: Principal = Depends(resolve_principal)) -> Principal:
    """Guard for routes a guest must never reach (e.g. creating documents).

    Currently a formality — resolve_principal only ever returns kind="user"
    until Phase 8 adds guest tokens — but it's where that guard belongs once
    that stops being true, so routes depend on this rather than inlining
    the check themselves.
    """
    if principal.kind != "user" or principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return principal


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

        granted = Access.NONE
        if principal.kind == "user" and principal.user_id == document.owner_id:
            granted = Access.OWNER
        # Guest/share-link branch lands in Phase 8: look up
        # principal.share_link_id, verify it's not revoked/expired and
        # matches document_id, and grant share_links.permission instead of
        # Access.NONE.

        if _ACCESS_RANK[granted] < _ACCESS_RANK[minimum]:
            # Never 403 — a stranger shouldn't learn the document exists.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

        return document, granted

    return _dependency
