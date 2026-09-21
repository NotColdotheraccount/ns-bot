"""Data access for topic bindings.

The repository holds every SQL statement touching topic_bindings. Handlers and
services call these methods instead of writing queries inline, so the storage
details stay in one file.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TopicBinding


class BindingRepository:
    """CRUD operations for TopicBinding rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[TopicBinding]:
        result = await self._session.execute(
            select(TopicBinding).order_by(TopicBinding.feature)
        )
        return list(result.scalars().all())

    async def get(self, group_id: int, thread_id: int) -> TopicBinding | None:
        result = await self._session.execute(
            select(TopicBinding).where(
                TopicBinding.group_id == group_id,
                TopicBinding.message_thread_id == thread_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        group_id: int,
        thread_id: int,
        feature: str,
        topic_title: str | None,
        user_id: int,
    ) -> TopicBinding:
        """Create the binding, or overwrite the feature if the topic is taken.

        Re-binding an already-bound topic is treated as a correction rather than
        an error: running /bind twice with different features should just work.
        """
        existing = await self.get(group_id, thread_id)
        if existing is not None:
            existing.feature = feature
            existing.topic_title = topic_title
            existing.bound_by_user_id = user_id
            await self._session.flush()
            return existing

        binding = TopicBinding(
            group_id=group_id,
            message_thread_id=thread_id,
            feature=feature,
            topic_title=topic_title,
            bound_by_user_id=user_id,
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def delete(self, group_id: int, thread_id: int) -> bool:
        """Remove a binding. Returns True if a row was actually deleted."""
        result = await self._session.execute(
            delete(TopicBinding).where(
                TopicBinding.group_id == group_id,
                TopicBinding.message_thread_id == thread_id,
            )
        )
        return bool(result.rowcount)
