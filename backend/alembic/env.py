import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.base import Base

# Import every model module here so Base.metadata is populated for
# autogenerate. Add to this list as models land in later phases.
# `comment` was missing from Phase 7 through Phase 8 — autogenerate was
# silently blind to it, which would have shown up as a spurious "drop the
# comments table" the first time anyone ran --autogenerate.
from app.models import (  # noqa: F401
    chat,
    comment,
    document,
    document_chunk,
    guest_session,
    password_reset_token,
    refresh_token,
    share_link,
    user,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Alembic always runs against the SESSION pooler (5432), never the
# transaction pooler the app uses at runtime.
MIGRATION_URL = settings.MIGRATION_DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=MIGRATION_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(MIGRATION_URL, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
