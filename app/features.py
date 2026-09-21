"""The canonical list of features a Telegram topic can be bound to.

This enum is the single source of truth for feature identifiers. Handlers,
the /bind command, and the scheduler all refer to these members rather than
raw strings, so a typo becomes an import error instead of a topic that
silently never responds.

Important: these identifiers are internal. The Telegram topic can be renamed
to anything at any time — "💌 #MissMe" today, "💌 my favourite place" next
month — and nothing breaks, because the binding is stored against the topic's
numeric thread ID, not its title.
"""

from __future__ import annotations

from enum import StrEnum


class Feature(StrEnum):
    """Every feature that can own a topic."""

    MISS_ME = "miss_me"
    VOICE = "voice"
    SONGS = "songs"
    REASSURANCE = "reassurance"
    BAD_DAY = "bad_day"
    AI_CHAT = "ai_chat"
    MEMORIES = "memories"
    OPEN_WHEN = "open_when"
    GOOD_MORNING = "good_morning"
    GOODNIGHT = "goodnight"
    DAILY_CHECKIN = "daily_checkin"
    MESSAGES_FOR_ME = "messages_for_me"
    COUNTDOWN = "countdown"
    LETTERS = "letters"
    SURPRISE = "surprise"
    ASK_PAST_ME = "ask_past_me"

    @property
    def label(self) -> str:
        """Human-friendly name for admin output, e.g. 'Miss Me'."""
        return self.value.replace("_", " ").title()

    @classmethod
    def parse(cls, raw: str) -> "Feature | None":
        """Convert user input into a Feature, or None if unrecognised."""
        candidate = raw.strip().lower().lstrip("#").replace("-", "_").replace(" ", "_")
        try:
            return cls(candidate)
        except ValueError:
            return None
