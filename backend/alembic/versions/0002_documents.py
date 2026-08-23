"""documents table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("doc_type", sa.Text(), nullable=True),
        sa.Column("key_points", postgresql.JSONB(), nullable=True),
        sa.Column("summary_embedding", Vector(768), nullable=True),
        sa.Column("extracted_chars", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_documents_owner_id_created_at",
        "documents",
        ["owner_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_documents_filename_trgm",
        "documents",
        ["filename"],
        postgresql_using="gin",
        postgresql_ops={"filename": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_documents_filename_trgm", table_name="documents")
    op.drop_index("ix_documents_owner_id_created_at", table_name="documents")
    op.drop_table("documents")
