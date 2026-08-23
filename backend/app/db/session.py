"""Async SQLAlchemy engine and session factory.

## Why this is pooled despite pgbouncer

Supabase's transaction-mode pgbouncer (port 6543) does not support prepared
statements. The setting that makes the app compatible with it is
`statement_cache_size=0` — asyncpg then sends every query unprepared, so no
server-side statement ever outlives the transaction pgbouncer hands us.

Connection pooling is a separate concern and is safe here. An earlier
revision used NullPool as belt-and-braces on top, which meant every single
query paid a fresh TCP handshake plus TLS negotiation to the database
region. From a client far from the database that is ~2s per query, so a
page issuing three queries spent six seconds doing nothing but connecting.

The pool is deliberately small. This runs on one uvicorn worker on a 512 MB
instance, and Supabase's pooler is itself shared — twenty idle connections
from one API would be antisocial and buy nothing at this concurrency.

`pool_pre_ping` matters more than usual: pgbouncer and the platform both
drop idle connections, and without it the first request after a quiet spell
fails on a dead socket instead of transparently reconnecting.

Alembic migrations use MIGRATION_DATABASE_URL (session pooler, port 5432)
instead — see alembic/env.py.

## The streaming trap

Inside SSE generators and background tasks, do NOT reuse a Depends(get_db)
session — FastAPI closes yield-dependencies before those run. Open your own:
    async with async_session_maker() as db: ...
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    # Non-negotiable for pgbouncer transaction mode. Removing this is what
    # would actually break; the pool below is unrelated to that constraint.
    connect_args={"statement_cache_size": 0},
    pool_size=5,
    max_overflow=5,
    # Hand back a live connection or reconnect — never a socket pgbouncer
    # closed while we were idle.
    pool_pre_ping=True,
    # Recycle well inside typical idle timeouts rather than discovering them.
    pool_recycle=1800,
    echo=False,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
