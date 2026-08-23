"""Comments — PROJECT_PLAN.md §2, §3.

Its own router with fully-qualified paths rather than a prefix, because the
three routes don't share one: two hang off /documents/{document_id} (so
require_document_access can bind document_id straight from the path) and
DELETE addresses the comment directly.

Threading is one level. A reply to a reply is rejected rather than silently
re-parented, so the tree the GET returns can never be deeper than the UI
knows how to draw.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Access, Principal, require_document_access, resolve_principal
from app.db.session import get_db
from app.models.comment import Comment
from app.models.document import Document
from app.models.user import User
from app.schemas.comment import CommentCreateRequest, CommentResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["comments"])

DELETED_LABEL = "[deleted]"


def _to_response(
    comment: Comment,
    *,
    document_owner_id: uuid.UUID,
    principal: Principal,
    replies: list[CommentResponse],
) -> CommentResponse:
    is_deleted = comment.deleted_at is not None
    is_mine = (
        principal.user_id is not None and comment.author_user_id == principal.user_id
    )
    caller_owns_document = principal.user_id == document_owner_id

    return CommentResponse(
        id=comment.id,
        parent_id=comment.parent_id,
        # A tombstone carries no author identity and no body. Retaining the
        # row is about keeping replies attached, not about keeping the text
        # recoverable by anyone who can read the thread.
        author_label=DELETED_LABEL if is_deleted else comment.author_label,
        body_markdown="" if is_deleted else comment.body_markdown,
        page_number=None if is_deleted else comment.page_number,
        created_at=comment.created_at,
        is_deleted=is_deleted,
        is_document_owner=(
            not is_deleted and comment.author_user_id == document_owner_id
        ),
        is_mine=not is_deleted and is_mine,
        # Nothing to delete twice; otherwise the author or the document owner.
        can_delete=not is_deleted and (is_mine or caller_owns_document),
        replies=replies,
    )


@router.get(
    "/documents/{document_id}/comments",
    response_model=list[CommentResponse],
)
async def list_comments(
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
    principal: Principal = Depends(resolve_principal),
    db: AsyncSession = Depends(get_db),
) -> list[CommentResponse]:
    document, _granted = access

    result = await db.execute(
        select(Comment)
        .where(Comment.document_id == document.id)
        .order_by(Comment.created_at.asc())
    )
    all_comments = list(result.scalars().all())

    # Group replies under their parent, preserving chronological order.
    replies_by_parent: dict[uuid.UUID, list[Comment]] = {}
    roots: list[Comment] = []
    for comment in all_comments:
        if comment.parent_id is None:
            roots.append(comment)
        else:
            replies_by_parent.setdefault(comment.parent_id, []).append(comment)

    tree: list[CommentResponse] = []
    for root in roots:
        # A deleted reply has nothing hanging off it (threading is one level),
        # so it's dropped outright rather than left as a tombstone.
        live_replies = [
            reply for reply in replies_by_parent.get(root.id, []) if reply.deleted_at is None
        ]

        # A deleted root is kept ONLY to hold its surviving replies together;
        # with none left there's nothing to anchor and it disappears.
        if root.deleted_at is not None and not live_replies:
            continue

        tree.append(
            _to_response(
                root,
                document_owner_id=document.owner_id,
                principal=principal,
                replies=[
                    _to_response(
                        reply,
                        document_owner_id=document.owner_id,
                        principal=principal,
                        replies=[],
                    )
                    for reply in live_replies
                ],
            )
        )

    return tree


@router.post(
    "/documents/{document_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    body: CommentCreateRequest,
    access: tuple[Document, Access] = Depends(require_document_access(Access.COMMENT)),
    principal: Principal = Depends(resolve_principal),
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    document, _granted = access

    if body.parent_id is not None:
        parent = await db.get(Comment, body.parent_id)
        # Checking document_id too stops a comment on document A being used
        # as the parent of a comment on document B.
        if parent is None or parent.document_id != document.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent comment not found")
        if parent.parent_id is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Replies are one level deep — reply to the top-level comment instead.",
            )
        if parent.deleted_at is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "That comment has been deleted."
            )

    # Guest authorship (guest_session_id + the guest's display name) lands in
    # Phase 8; until then require_document_access only ever grants access to
    # a signed-in user, so author_user_id is always present here.
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    author = await db.get(User, principal.user_id)
    if author is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    comment = Comment(
        document_id=document.id,
        parent_id=body.parent_id,
        author_user_id=principal.user_id,
        # Denormalised at write time: the label should reflect who posted it,
        # even if the account is renamed later.
        author_label=author.name,
        body_markdown=body.body_markdown,
        page_number=body.page_number,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return _to_response(
        comment,
        document_owner_id=document.owner_id,
        principal=principal,
        replies=[],
    )


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    principal: Principal = Depends(resolve_principal),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft delete. Author or document owner only.

    This route can't use require_document_access — it's addressed by comment
    id, so there's no {document_id} in the path for that dependency to bind.
    The document is loaded here and the same fail-closed rule applies: every
    refusal is a 404, so nobody learns a comment exists that they can't touch.
    """
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")

    document = await db.get(Document, comment.document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")

    is_author = (
        principal.user_id is not None and comment.author_user_id == principal.user_id
    )
    is_document_owner = principal.user_id == document.owner_id
    if not (is_author or is_document_owner):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")

    # Idempotent: deleting an already-deleted comment is a no-op, not a 409.
    if comment.deleted_at is None:
        comment.deleted_at = datetime.now(timezone.utc)
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
