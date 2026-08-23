"""chat_sessions and chat_messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23

A session belongs to exactly one principal — a signed-in user OR a guest
session, never both and never neither. That CHECK is not decoration: the
chat routes authorise history reads by comparing the caller's principal
against these two columns, and a row with both null would be readable by
nobody while a row with both set would be readable by two different people.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Same CASCADE reasoning as comments.guest_session_id: the CHECK
        # below makes SET NULL impossible on a guest-owned row.
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("guest_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR guest_session_id IS NOT NULL",
            name="ck_chat_sessions_has_principal",
        ),
    )
    op.create_index(
        "ix_chat_sessions_document_id_created_at",
        "chat_sessions",
        ["document_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # [{chunk_id, page_start, page_end}] — persisted so reopening a
        # conversation restores clickable citations rather than plain text
        # that merely looks like it once had them.
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_chat_messages_role"
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_document_id_created_at", table_name="chat_sessions")
    op.drop_table("chat_sessions")
