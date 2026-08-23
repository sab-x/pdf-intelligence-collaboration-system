from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models. Import every model module in
    alembic/env.py before autogenerate so Base.metadata sees them all."""
