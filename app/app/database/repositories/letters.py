"""Data access for letter delivery state."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LetterState


class LetterRepository:
    """Tracks which letters have already been delivered."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sent_ids(self) -> set[str]:
        result = await self._session.execute(select(LetterState.letter_id))
        return set(result.scalars().all())

    async def was_sent(self, letter_id: str) -> bool:
        return await self._session.get(LetterState, letter_id) is not None

    async def mark_sent(self, letter_id: str, number: int) -> bool:
        """Record delivery. Returns False if it was already recorded."""
        if await self._session.get(LetterState, letter_id) is not None:
            return False
        self._session.add(LetterState(letter_id=letter_id, number=number))
        await self._session.flush()
        return True

    async def unmark(self, letter_id: str) -> bool:
        """Undo a delivery record, so a letter can be re-sent. Admin only."""
        row = await self._session.get(LetterState, letter_id)
        if row is None:
            return False
        await self._session.delete(row)
        return True

    async def recent(self, limit: int = 10) -> list[LetterState]:
        result = await self._session.execute(
            select(LetterState).order_by(desc(LetterState.sent_at)).limit(limit)
        )
        return list(result.scalars().all())
