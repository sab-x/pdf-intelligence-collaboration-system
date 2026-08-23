import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class ChatSession(Base):
    """One conversation about one document — PROJECT_PLAN.md §2.

    Owned by exactly one principal: `user_id` XOR `guest_session_id`,
    enforced by ck_chat_sessions_has_principal.

    This ownership is a SECOND authorization check, independent of
    require_document_access. Document access decides whether you may see the
    document; it says nothing about whose conversation you may read. Without
    the extra check a guest holding a valid share link could read the
    owner's private chat history by guessing a session id — see
    PROJECT_PLAN.md §3 and the test in §11.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR guest_session_id IS NOT NULL",
            name="ck_chat_sessions_has_principal",
        ),
        Index(
            "ix_chat_sessions_document_id_created_at",
            "document_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guest_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ChatMessage(Base):
    """One turn. Both the user's question and the assistant's answer are
    rows here, distinguished by `role`.

    `citations` holds [{chunk_id, page_start, page_end}] for assistant
    turns. Persisted rather than recomputed because reopening a conversation
    has to restore the clickable [p. N] chips — re-running retrieval later
    could return different chunks and silently rewrite history.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
