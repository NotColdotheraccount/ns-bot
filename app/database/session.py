"""Database engine and session management.

Wrapped in a class rather than exposed as module-level globals. A global engine
is created at import time, which makes tests awkward and hides the application's
startup and shutdown order.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.base import Base

logger = logging.getLogger(__name__)


class Database:
    """Owns the async engine and hands out sessions."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=echo)
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,  # keep objects usable after commit
        )

    async def create_all(self) -> None:
        """Create any missing tables.

        Adequate for this project: SQLite, single developer, additive schema
        changes. It does NOT alter existing tables, so if a column is added to
        a model later, that needs a real migration. Alembic is the tool for
        that, and adding it now would be overhead for no benefit.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema ready.")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, committing on success and rolling back on error."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """Close all pooled connections. Called during shutdown."""
        await self._engine.dispose()
