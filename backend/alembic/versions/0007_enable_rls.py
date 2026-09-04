"""enable row level security on all public tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-01

## Why this exists

Supabase's Security Advisor flags every table in `public` as CRITICAL when
RLS is off, because Supabase auto-exposes the entire `public` schema through
PostgREST — anyone holding the project's `anon` key can otherwise query
these tables directly over HTTP, completely bypassing this app's own
authorization.

This app was never designed around Supabase Auth/RLS — access control is
enforced entirely in the API layer (`require_document_access()` and
friends), and the frontend never talks to Supabase directly; it only ever
calls this backend. So in practice the PostgREST hole was unused, not
actively exploited. But "unused" isn't the same as "closed", and leaving it
open only costs an anon key leaking (client bundles, logs, a misconfigured
tool) for it to become a real hole — every one of these tables would be
fully readable and writable with no auth at all.

## Why this is safe to ship with zero policies

Enabling RLS with no policies attached makes a table default-deny for every
role EXCEPT one with the BYPASSRLS attribute or the table owner under
FORCE RLS (not used here). Supabase's `postgres` role — the one this app's
own `DATABASE_URL` connects as — has BYPASSRLS by default. So this
migration changes nothing observable for the running application: every
query this backend issues keeps working exactly as before. What it removes
is PostgREST's ability to read or write these tables using the `anon` or
`authenticated` roles, which this app never uses anyway.

No policies are added because none are needed: this isn't "let users see
their own rows via Supabase," it's "make sure nobody can see ANY row except
through this backend's own auth."
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "users",
    "refresh_tokens",
    "documents",
    "comments",
    "share_links",
    "guest_sessions",
    "document_chunks",
    "chat_sessions",
    "chat_messages",
    "alembic_version",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;")
