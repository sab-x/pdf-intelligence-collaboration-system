"""Pytest fixtures for the auth test suite.

Tests run against a DEDICATED test database — never the app's real
DATABASE_URL from backend/.env. Set TEST_DATABASE_URL to point this at your
own throwaway Postgres database; otherwise it defaults to a local
`pdfintel_test` database on localhost. The env vars below are set BEFORE any
`app.*` module is imported, so the app's own engine (app/db/session.py) ends
up bound to the test DB automatically — no dependency override needed.

Schema is created directly from the ORM metadata (vector/pg_trgm/citext
extensions + every table) rather than by running the Alembic migration. As
of Phase 3, the documents table's summary_embedding column and filename
trigram index mean vector and pg_trgm are both required here too, not just
citext. Phase 9's document_chunks adds an HNSW index and a generated
tsvector column, so the test database needs a pgvector new enough for HNSW
(>= 0.5) — the same requirement as production.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/pdfintel_test",
)
os.environ["MIGRATION_DATABASE_URL"] = os.environ["DATABASE_URL"]
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-do-not-use-in-production-000")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")

import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.limiter import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402,F401
    chat,
    comment,
    document,
    document_chunk,
    guest_session,
    refresh_token,
    share_link,
    user,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        # Every table any test writes to. Missing one here doesn't fail the
        # test that created the row — it fails some unrelated later test
        # with a duplicate-key or leftover-state error that points nowhere
        # near the cause, so this list has to stay in step with the models.
        await conn.execute(
            text(
                "TRUNCATE TABLE chat_messages, chat_sessions, document_chunks, "
                "comments, guest_sessions, share_links, refresh_tokens, "
                "users, documents CASCADE"
            )
        )


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    # The Limiter in app/core/limiter.py is a module-level singleton with
    # in-memory storage (slowapi's default "memory://" backend), so its
    # per-IP counters persist across tests in the same process. Every
    # request from the ASGI test transport looks like it comes from the
    # same address, so without this reset the 5th signup/login call in the
    # whole suite trips RATE_LIMIT_AUTH (5/minute) and returns 429 instead
    # of the status code the test actually expects. This resets the
    # in-memory counters only — the limit values and production wiring in
    # app/core/limiter.py and main.py are untouched.
    limiter.reset()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # base_url uses https:// so httpx's cookie jar will actually store and
    # resend the refresh cookie, which the app sets with Secure=True.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as ac:
        yield ac


@pytest.fixture
def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"
