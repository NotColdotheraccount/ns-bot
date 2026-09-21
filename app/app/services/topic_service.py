"""Resolves a Telegram topic to the feature that owns it.

Bindings live in SQLite but are cached in memory. Every incoming group message
needs a lookup, and hitting the database on each one would add latency for data
that changes a handful of times in the project's life.

The cache is authoritative for reads and refreshed on every write, so it cannot
drift from the database within a single running process.
"""

from __future__ import annotations

import logging

from app.database.repositories.bindings import BindingRepository
from app.database.session import Database
from app.features import Feature

logger = logging.getLogger(__name__)

# (group_id, message_thread_id) -> Feature
_CacheKey = tuple[int, int]


class TopicService:
    """In-memory view of topic bindings, backed by SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[_CacheKey, Feature] = {}
        self._titles: dict[_CacheKey, str | None] = {}

    async def load(self) -> None:
        """Populate the cache from the database. Called once at startup."""
        self._cache.clear()
        self._titles.clear()

        async with self._db.session() as session:
            rows = await BindingRepository(session).list_all()

        skipped = 0
        for row in rows:
            feature = Feature.parse(row.feature)
            if feature is None:
                # A feature was renamed or removed from the enum while a row
                # still referenced it. Skip rather than crash — the bot should
                # start with 14 working topics rather than not start at all.
                logger.warning(
                    "Ignoring binding with unknown feature | thread=%s feature=%r",
                    row.message_thread_id,
                    row.feature,
                )
                skipped += 1
                continue
            key = (row.group_id, row.message_thread_id)
            self._cache[key] = feature
            self._titles[key] = row.topic_title

        logger.info("Loaded %d topic bindings (%d skipped).", len(self._cache), skipped)

    def resolve(self, group_id: int, thread_id: int | None) -> Feature | None:
        """Return the feature bound to this topic, if any.

        thread_id is None for direct messages and for a forum's General topic.
        Neither can own a feature, so both resolve to None.
        """
        if thread_id is None:
            return None
        return self._cache.get((group_id, thread_id))

    def thread_for(self, feature: Feature) -> int | None:
        """Reverse lookup: which thread owns this feature.

        Used by the scheduler to find where a morning message should be posted.
        If several topics share a feature, the lowest thread ID wins so the
        destination stays stable across restarts.
        """
        threads = [
            thread_id
            for (_group, thread_id), bound in self._cache.items()
            if bound is feature
        ]
        return min(threads) if threads else None

    def all_bindings(self) -> list[tuple[int, Feature, str | None]]:
        """Every binding as (thread_id, feature, title), sorted by feature."""
        items = [
            (thread_id, feature, self._titles.get((group_id, thread_id)))
            for (group_id, thread_id), feature in self._cache.items()
        ]
        return sorted(items, key=lambda item: item[1].value)

    async def bind(
        self,
        *,
        group_id: int,
        thread_id: int,
        feature: Feature,
        topic_title: str | None,
        user_id: int,
    ) -> None:
        """Persist a binding and update the cache."""
        async with self._db.session() as session:
            await BindingRepository(session).upsert(
                group_id=group_id,
                thread_id=thread_id,
                feature=feature.value,
                topic_title=topic_title,
                user_id=user_id,
            )

        key = (group_id, thread_id)
        self._cache[key] = feature
        self._titles[key] = topic_title
        logger.info("Bound thread=%s -> %s", thread_id, feature.value)

    async def unbind(self, *, group_id: int, thread_id: int) -> Feature | None:
        """Remove a binding. Returns the feature that was removed, or None."""
        async with self._db.session() as session:
            deleted = await BindingRepository(session).delete(group_id, thread_id)

        if not deleted:
            return None

        key = (group_id, thread_id)
        previous = self._cache.pop(key, None)
        self._titles.pop(key, None)
        logger.info("Unbound thread=%s (was %s)", thread_id, previous)
        return previous
