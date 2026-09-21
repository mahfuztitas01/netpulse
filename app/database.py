"""Async SQLAlchemy engine, session factory and base model."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# SQLite needs check_same_thread disabled only for sync; aiosqlite handles it.
_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_async_engine(
    settings.database_url_async,
    echo=False,
    future=True,
    pool_pre_ping=not settings.is_sqlite,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# Columns added after the first release: (table, column, SQL type).
# create_all() only creates missing *tables*, so new columns are patched here
# to keep existing databases working without a migration tool.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("devices", "alert_group_id", "INTEGER"),
]


def _migrate_columns(conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(conn)
    for table, column, ddl in _ADDED_COLUMNS:
        try:
            existing = {c["name"] for c in insp.get_columns(table)}
        except Exception:  # table does not exist yet
            continue
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    """Create tables and patch in columns added by newer versions."""
    # Import models so they are registered on Base.metadata.
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_columns)
