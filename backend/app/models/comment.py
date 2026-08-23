import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class Comment(Base):
    """A comment on a document — PROJECT_PLAN.md §2.

    Threading is exactly one level deep: a comment with parent_id set is a
    reply, and replies cannot themselves be replied to. That's enforced in
    the API layer rather than the schema, because SQL can't express
    "parent_id must point at a row whose own parent_id is null" without a
    trigger.
    """

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(
            "author_user_id IS NOT NULL OR guest_session_id IS NOT NULL",
            name="ck_comments_has_author",
        ),
        Index("ix_comments_document_id_created_at", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # The constraint 0003 deferred, attached in 0004 once guest_sessions
    # existed. CASCADE is forced rather than chosen: ck_comments_has_author
    # requires one of the two author columns to be non-null, so SET NULL on
    # a guest comment would violate it and abort the parent delete.
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guest_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    author_label: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
