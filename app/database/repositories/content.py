"""Data access for content send-state and history."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import utcnow
from app.database.models import ContentHistory, ContentState


class ContentRepository:
    """Reads and writes the runtime half of the content system."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def states_for(self, content_ids: list[str]) -> dict[str, ContentState]:
        """Fetch state rows for the given ids, keyed by content_id.

        Items never sent simply have no row, so the result may be smaller than
        the input. Callers treat a missing row as 'never sent'.
        """
        if not content_ids:
            return {}
        result = await self._session.execute(
            select(ContentState).where(ContentState.content_id.in_(content_ids))
        )
        return {row.content_id: row for row in result.scalars().all()}

    async def record_send(
        self, *, content_id: str, user_id: int, feature: str | None = None
    ) -> None:
        """Increment counters and append to history."""
        state = await self._session.get(ContentState, content_id)
        if state is None:
            state = ContentState(content_id=content_id, times_sent=0)
            self._session.add(state)

        state.times_sent += 1
        state.last_sent_at = utcnow()

        self._session.add(
            ContentHistory(content_id=content_id, user_id=user_id, feature=feature)
        )
        await self._session.flush()

    async def cache_file_id(self, content_id: str, file_id: str) -> None:
        """Store the Telegram file_id returned after a successful upload."""
        state = await self._session.get(ContentState, content_id)
        if state is None:
            state = ContentState(content_id=content_id, times_sent=0)
            self._session.add(state)
        state.telegram_file_id = file_id
        await self._session.flush()

    async def recent(self, limit: int = 10) -> list[ContentHistory]:
        result = await self._session.execute(
            select(ContentHistory).order_by(desc(ContentHistory.created_at)).limit(limit)
        )
        return list(result.scalars().all())
