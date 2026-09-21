"""Weighted, history-aware selection — shared by content and memories.

This logic started inside ContentSelector. Memories need exactly the same
behaviour (prefer unseen, suppress recent, respect author weight) over a
different object type, so rather than copy-pasting the scoring, it is extracted
here and both callers use it.

Worth noting *when* this extraction happened: on the second use case, not the
first. Generalising a single caller usually produces an abstraction shaped
around one example, which then fights you when the real second case arrives.
Two concrete cases is enough to see which parts genuinely vary — here, only the
type of the thing being picked.

The Selectable protocol is structural: anything with a string `id` and a float
`weight` works. No base class to inherit, no registration.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence, TypeVar, runtime_checkable

from app.database.models import ContentState

# How long an item is suppressed after being sent.
DEFAULT_COOLDOWN = timedelta(days=3)

# Multiplier applied to anything never sent. High on purpose: for a gift built
# from a finite set of recordings, she should see everything once before
# anything repeats.
UNSEEN_BONUS = 3.0

# Controls how strongly repeated sends are penalised. Higher = flatter.
USAGE_DAMPING = 0.5


@runtime_checkable
class Selectable(Protocol):
    """Anything pickable: needs a stable id and a relative weight."""

    id: str
    weight: float


T = TypeVar("T", bound=Selectable)


def last_sent_at(state: ContentState | None) -> datetime | None:
    """Read last_sent_at, forcing it to be timezone-aware.

    SQLite does not persist timezone information, so a datetime read back from
    the database arrives naive even though it was stored as UTC. Subtracting a
    naive datetime from an aware one raises TypeError, so it is re-tagged here
    — in one place, rather than at every call site.
    """
    if state is None or state.last_sent_at is None:
        return None
    value = state.last_sent_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def score_one(
    item: Selectable,
    state: ContentState | None,
    now: datetime,
    cooldown: timedelta,
) -> float:
    """Relative likelihood of choosing this item. Zero means 'not right now'."""
    if state is None or state.times_sent == 0:
        return item.weight * UNSEEN_BONUS

    # Novelty: 1/sqrt(times_sent). Decays gently, so a frequently sent item
    # becomes less likely without ever being ruled out entirely.
    score = item.weight / ((1 + state.times_sent) ** USAGE_DAMPING)

    sent = last_sent_at(state)
    if sent is not None:
        age = now - sent
        if age < cooldown:
            # Squared ramp: ~0 immediately after sending, rising smoothly back
            # to full weight by the end of the cooldown window.
            ratio = age / cooldown
            score *= ratio * ratio

    return max(score, 0.0)


def weighted_pick(
    candidates: Sequence[T],
    states: dict[str, ContentState],
    *,
    rng: random.Random,
    cooldown: timedelta = DEFAULT_COOLDOWN,
) -> T:
    """Choose one candidate, biased toward unseen and long-unsent items.

    Callers must ensure `candidates` is non-empty.
    """
    now = datetime.now(timezone.utc)
    scores = [score_one(item, states.get(item.id), now, cooldown) for item in candidates]

    if sum(scores) <= 0.0:
        # Everything is inside its cooldown. Fall back to whatever has been
        # unseen longest rather than returning nothing: repeating something is
        # always better than the bot going silent on her.
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        return min(candidates, key=lambda item: last_sent_at(states.get(item.id)) or oldest)

    return rng.choices(list(candidates), weights=scores, k=1)[0]
