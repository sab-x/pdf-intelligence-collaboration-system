import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class DocumentChunk(Base):
    """One retrievable slice of a document — PROJECT_PLAN.md §2, §7.

    Carries both retrieval representations side by side: `embedding` for
    vector similarity and `tsv` for full-text. Reciprocal rank fusion joins
    the two result sets on `id`, which only works cheaply because they live
    on the same row.

    `page_start` / `page_end` are 1-based and inclusive. They are the entire
    reason chunking is page-aware rather than operating on one flat string:
    without them a grounded answer can quote the document but can't tell the
    reader where to look, and the [p. N] citation — the thing that makes the
    RAG visible — has nothing to point at.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_id_chunk_index"
        ),
        Index("ix_document_chunks_document_id_chunk_index", "document_id", "chunk_index"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)

    # Dimension must equal settings.EMBED_DIM. Hardcoded here to match
    # documents.summary_embedding and the migration — a model that read the
    # setting could silently disagree with the column the database actually
    # has, which surfaces as an opaque insert error rather than a config
    # mistake. Change all three together or not at all.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    # Maintained by Postgres from `content`. Declared read-only here so
    # SQLAlchemy never tries to write it.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
