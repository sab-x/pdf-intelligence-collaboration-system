"""password_reset_tokens

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-04

Password reset was a declared, deliberate cut for the original 3-day
submission (see README's Known Limitations) — this is the follow-up. The
table mirrors refresh_tokens' issue/invalidate lifecycle on purpose.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )
    # New table in the public schema — enable RLS immediately rather than
    # waiting for the next advisor scan to flag it. Zero policies, same
    # reasoning as migration 0007: this app's own connection bypasses RLS
    # via the postgres role, so nothing changes for the running app.
    op.execute("ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
