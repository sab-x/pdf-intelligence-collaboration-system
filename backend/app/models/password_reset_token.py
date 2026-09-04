import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base


class PasswordResetToken(Base):
    """One row per issued reset link.

    Mirrors RefreshToken's shape deliberately: same "issue, invalidate,
    never delete" lifecycle, so a security reviewer sees the same audit
    trail pattern rather than a novel one for this table.

    `token_hash`, never the raw token — see security.hash_reset_token. If
    this table ever leaked, the raw tokens (the only thing usable to
    actually reset a password) are not in it.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set the instant the token is spent. A used-but-unexpired token must
    # never verify a second time — this column, checked IS NULL, is what
    # makes a reset link single-use rather than valid-until-expiry.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
