import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class ShareLink(Base):
    """A revocable public link granting account-less access to one document.

    Revocation is a soft delete: DELETE /shares/{id} sets `revoked_at` and
    leaves the row in place. That matters for two reasons — guest comments
    stay attributed (the guest_sessions rows they point at survive), and the
    token stays permanently burned rather than becoming reusable if an
    identical one were ever minted again.

    `permission` is constrained to the closed set at the database level as
    well as here. A value outside it would reach require_document_access and
    blow up on Access(...) construction rather than silently degrading to no
    access, but the CHECK means it can't get in at all.
    """

    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('view', 'comment')",
            name="ck_share_links_permission",
        ),
        Index(
            "ix_share_links_document_id_created_at",
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
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # secrets.token_urlsafe(32) — 256 bits, ~43 chars. UNIQUE doubles as the
    # lookup index for GET /share/{token}.
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    permission: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'comment'")
    )
    # Captured and stored; actually sending the invitation is out of scope.
    invited_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    def is_live(self, *, now: datetime) -> bool:
        """True when this link still grants access.

        Kept on the model rather than inlined in the dependency so the
        access rule has exactly one definition — require_document_access,
        the public share route, and the guest-session route all ask the same
        question and can never drift apart on, say, whether an expiry that
        falls exactly now counts as expired.
        """
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True
