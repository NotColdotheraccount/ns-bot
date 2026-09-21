"""Chooses which piece of content to send, without repeating itself.

Your spec asked for one ContentSelector rather than random logic scattered
through fifteen handlers. This is it. Every feature that picks something calls
`choose()`, so the anti-repetition behaviour is identical everywhere and can be
tuned in one place.

The scoring itself lives in app/services/scoring.py, shared with memory
selection. See that module for why uniform random is not good enough and how
the weighting works.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta

from app.content.library import ContentLibrary
from app.content.schema import ContentItem, ContentKind
from app.database.repositories.content import ContentRepository
from app.database.session import Database
from app.services.scoring import DEFAULT_COOLDOWN, weighted_pick

logger = logging.getLogger(__name__)

# How long an item is suppressed after being sent. Three days is a compromise:
# long enough that repeats are not noticeable, short enough that a library of
# ~15 items does not run dry.
DEFAULT_COOLDOWN = timedelta(days=3)

# Multiplier applied to content that has never been sent.
UNSEEN_BONUS = 3.0

# Controls how strongly repeated sends are penalised. Higher = flatter.
USAGE_DAMPING = 0.5


class ContentSelector:
    """Weighted, history-aware content picker."""

    def __init__(
        self,
        library: ContentLibrary,
        database: Database,
        cooldown: timedelta = DEFAULT_COOLDOWN,
        rng: random.Random | None = None,
    ) -> None:
        self._library = library
        self._db = database
        self._cooldown = cooldown
        # Injectable RNG so tests can be deterministic. Production passes None
        # and gets the module-level random instance.
        self._rng = rng or random.Random()

    # ----------------------------------------------------------------- public

    async def choose(
        self,
        *,
        kinds: tuple[ContentKind, ...] = (),
        tags: tuple[str, ...] = (),
        exclude_ids: tuple[str, ...] = (),
        require_all_tags: bool = False,
    ) -> ContentItem | None:
        """Pick one item matching the filters, or None if nothing matches.

        `exclude_ids` is for within-a-single-reply de-duplication — when Miss Me
        sends a reassurance plus a voice note, the second pick excludes the first.
        """
        candidates = self._library.select(
            kinds=kinds, tags=tags, require_all_tags=require_all_tags
        )
        if exclude_ids:
            excluded = set(exclude_ids)
            candidates = [item for item in candidates if item.id not in excluded]

        if not candidates:
            logger.info(
                "No content matched | kinds=%s tags=%s",
                [k.value for k in kinds],
                list(tags),
            )
            return None

        async with self._db.session() as session:
            states = await ContentRepository(session).states_for(
                [item.id for item in candidates]
            )

        return weighted_pick(candidates, states, rng=self._rng, cooldown=self._cooldown)

    async def choose_many(
        self,
        count: int,
        *,
        kinds: tuple[ContentKind, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> list[ContentItem]:
        """Pick several distinct items, e.g. a reassurance plus a voice note."""
        chosen: list[ContentItem] = []
        for _ in range(count):
            item = await self.choose(
                kinds=kinds,
                tags=tags,
                exclude_ids=tuple(picked.id for picked in chosen),
            )
            if item is None:
                break
            chosen.append(item)
        return chosen

    async def record_sent(
        self, item: ContentItem, *, user_id: int, feature: str | None = None
    ) -> None:
        """Mark an item as delivered. Call only after Telegram accepted it.

        Recording before the send would let a failed upload permanently suppress
        a piece of content she never actually received.
        """
        async with self._db.session() as session:
            await ContentRepository(session).record_send(
                content_id=item.id, user_id=user_id, feature=feature
            )
