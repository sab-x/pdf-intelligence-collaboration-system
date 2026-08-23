"""comments table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comments",
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
        # One-level threading (good-to-have #3). CASCADE so deleting a parent
        # row would take its replies with it — note that ordinary deletion in
        # this app is SOFT (deleted_at), so this only fires if a row is ever
        # hard-deleted administratively.
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Phase 8 stub. The guest_sessions table does not exist yet, so this
        # deliberately carries NO foreign key — adding one here would make
        # this migration fail on a fresh database. Phase 8 creates
        # guest_sessions and adds the FK constraint in its own migration.
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Denormalised display name: a guest has no user row to join to, and
        # a comment should keep the name it was posted under even if the
        # author later changes theirs.
        sa.Column("author_label", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Soft delete: the row survives so replies aren't orphaned.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "author_user_id IS NOT NULL OR guest_session_id IS NOT NULL",
            name="ck_comments_has_author",
        ),
    )
    op.create_index(
        "ix_comments_document_id_created_at",
        "comments",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_comments_document_id_created_at", table_name="comments")
    op.drop_table("comments")
