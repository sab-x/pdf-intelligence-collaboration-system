"""document_chunks: vector + full-text retrieval foundation

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23

Both halves of the hybrid retrieval in PROJECT_PLAN.md §7 live on this one
table: `embedding` for the vector side, `tsv` for the lexical side. Keeping
them together is what lets reciprocal rank fusion join the two result sets
on chunk id without a second lookup.

`vector` and `pg_trgm` already exist — migration 0002 created
documents.summary_embedding and a trigram index, so neither extension is
created here.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
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
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # 1-based and inclusive, matching what a citation renders: a chunk
        # spanning one page has page_start == page_end, and "[p. 4]" is
        # exactly page_start.
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        # Approximate — see services/chunking.py on why there is no exact
        # token count without a Gemini tokenizer. Stored for observability,
        # never for correctness.
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        # NULLable on purpose. If the embedding API fails, ingestion still
        # writes the chunks and the document still becomes 'ready' — the
        # lexical half of retrieval keeps working and only the vector half
        # degrades. Failing a whole document over one API timeout would
        # throw away a perfectly good summary.
        sa.Column("embedding", Vector(768), nullable=True),
        # GENERATED, not trigger-maintained: Postgres recomputes it on every
        # write of `content`, so the index physically cannot drift out of
        # sync with the text it indexes.
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Re-ingesting a document deletes its chunks and rewrites them from
        # index 0, so this both enforces ordering and catches a partial
        # rewrite that left stale rows behind.
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_id_chunk_index"
        ),
    )

    # HNSW over cosine distance. Built on an empty table, which is instant —
    # doing it here rather than after backfilling avoids a long lock later.
    # vector_cosine_ops must match the operator the query uses (<=>), or the
    # planner silently ignores the index and sequential-scans every chunk.
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_index(
        "ix_document_chunks_tsv",
        "document_chunks",
        ["tsv"],
        postgresql_using="gin",
    )

    # Retrieval is always scoped to one document, so every query filters on
    # document_id first. Ordered by chunk_index because assembling context
    # for the LLM reads them in document order.
    op.create_index(
        "ix_document_chunks_document_id_chunk_index",
        "document_chunks",
        ["document_id", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_id_chunk_index", table_name="document_chunks")
    op.drop_index("ix_document_chunks_tsv", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_table("document_chunks")
