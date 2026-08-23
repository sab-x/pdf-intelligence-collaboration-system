"""Async SQLAlchemy engine and session factory.

Supabase's transaction-mode pgbouncer (port 6543) does not support prepared
statements, so the engine is created with statement_cache_size=0 + NullPool.
Alembic migrations use MIGRATION_DATABASE_URL (session pooler, port 5432)
instead — see alembic/env.py.

Inside SSE generators and background tasks, do NOT reuse a Depends(get_db)
session — FastAPI closes yield-dependencies before those run. Open your own:
    async with async_session_maker() as db: ...
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"statement_cache_size": 0},
    poolclass=NullPool,
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
