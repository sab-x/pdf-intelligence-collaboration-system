"""share_links and guest_sessions; attach the deferred comments FK

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23

Migration 0003 created comments.guest_session_id WITHOUT a foreign key,
because guest_sessions did not exist yet. This migration creates that table
and finally attaches the constraint, so the column stops being unpoliced.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "share_links",
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
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # secrets.token_urlsafe(32) -> 256 bits of entropy, ~43 chars.
        # UNIQUE gives us the lookup index the plan asks for at the same time.
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "permission",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'comment'"),
        ),
        # Captured and stored; actually sending it is out of scope (§0).
        sa.Column("invited_email", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "view_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The permission ladder is a closed set. Enforcing it here means a bad
        # value can't reach require_document_access and be silently treated as
        # "no access" — or worse, be added later without updating the ladder.
        sa.CheckConstraint(
            "permission IN ('view', 'comment')",
            name="ck_share_links_permission",
        ),
    )
    # Owner-facing "list the links on this document", newest first.
    op.create_index(
        "ix_share_links_document_id_created_at",
        "share_links",
        ["document_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "guest_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "share_link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("share_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # The constraint deferred by migration 0003, now that its target exists.
    #
    # CASCADE is forced, not chosen. comments.ck_comments_has_author requires
    # author_user_id OR guest_session_id to be non-null; a guest comment has
    # only the latter, so SET NULL would violate the check and abort the
    # parent delete. RESTRICT would block document deletion outright once any
    # guest had commented. CASCADE is the only rule compatible with the
    # constraint sitting beside it.
    #
    # Note what this does NOT do: revoking a share link sets revoked_at and
    # leaves the row in place, so this cascade never fires on revocation and
    # guest comments survive it. It runs only on a genuine DELETE further up
    # the chain — users -> documents -> share_links -> guest_sessions -> comments
    # — where documents.id already reaps the same comments directly. Here it
    # is a backstop, not the mechanism.
    op.create_foreign_key(
        "fk_comments_guest_session_id",
        source_table="comments",
        referent_table="guest_sessions",
        local_cols=["guest_session_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_comments_guest_session_id", "comments", type_="foreignkey")
    op.drop_table("guest_sessions")
    op.drop_index("ix_share_links_document_id_created_at", table_name="share_links")
    op.drop_table("share_links")
