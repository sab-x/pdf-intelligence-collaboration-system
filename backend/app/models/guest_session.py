import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class GuestSession(Base):
    """Identity for an account-less invitee — PROJECT_PLAN.md §2.

    Created when a guest submits a display name on the share page. It is the
    thing a guest's comments are attributed to, which is why it's a row and
    not just a claim in the JWT: comments outlive tokens, and the author
    label has to remain resolvable after the guest's 24-hour token expires.

    ON DELETE CASCADE from share_links, and comments cascade from here. That
    chain only fires when a share_links row is genuinely deleted — which
    revocation does not do — so in practice it runs only when the owner
    deletes the whole document. CASCADE rather than SET NULL is forced:
    comments.ck_comments_has_author requires at least one of author_user_id
    or guest_session_id to be non-null, so nulling this column on a guest
    comment would violate the check and abort the parent delete outright.
    """

    __tablename__ = "guest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    share_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("share_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
