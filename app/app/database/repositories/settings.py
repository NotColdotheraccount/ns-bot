"""Data access for runtime settings and daily check-ins."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BotSetting, CheckIn


class SettingsRepository:
    """Key-value settings with defaults."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str, default: str) -> str:
        row = await self._session.get(BotSetting, key)
        return row.value if row else default

    async def all(self) -> dict[str, str]:
        result = await self._session.execute(select(BotSetting))
        return {row.key: row.value for row in result.scalars().all()}

    async def set(self, key: str, value: str) -> None:
        row = await self._session.get(BotSetting, key)
        if row is None:
            self._session.add(BotSetting(key=key, value=value))
        else:
            row.value = value
        await self._session.flush()


class CheckInRepository:
    """Daily check-in answers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_date(self, local_date: str) -> CheckIn | None:
        result = await self._session.execute(
            select(CheckIn).where(CheckIn.local_date == local_date)
        )
        return result.scalar_one_or_none()

    async def record(self, *, local_date: str, mood: str, user_id: int) -> bool:
        """Store an answer. Returns False if that day already has one.

        Returning a flag rather than raising lets the handler give her a gentle
        "already answered" instead of an error.
        """
        existing = await self.for_date(local_date)
        if existing is not None:
            return False
        self._session.add(CheckIn(local_date=local_date, mood=mood, user_id=user_id))
        await self._session.flush()
        return True

    async def recent(self, limit: int = 14) -> list[CheckIn]:
        result = await self._session.execute(
            select(CheckIn).order_by(desc(CheckIn.local_date)).limit(limit)
        )
        return list(result.scalars().all())
