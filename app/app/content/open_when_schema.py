"""The shape of an Open When letter.

Physically these are the envelopes she opens when something specific happens.
Digitally: a titled letter she chooses from a list, rather than one the bot
picks for her. That difference matters — the whole point of an Open When is
that *she* decides which one she needs right now.

Unlocking is optional and off by default. A letter with no unlock rule is
available immediately. Your spec said not to make unlocking restrictive, and
the failure mode is real: a locked letter on the night she actually needs it
is worse than no lock at all.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpenWhen(BaseModel):
    """One Open When letter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=48)

    # Shown on the button. Keep it short — Telegram truncates long labels.
    title: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1)

    # Paths relative to media/.
    photo: str | None = None
    voice: str | None = None
    video: str | None = None

    # Optional follow-up sent a moment after the letter.
    followup: str | None = None

    # At most one unlock rule. Neither set = available immediately.
    unlock_on: date | None = None
    unlock_day: int | None = Field(default=None, ge=0)

    order: int = Field(default=100)
    enabled: bool = True

    @model_validator(mode="after")
    def _one_unlock_rule(self) -> OpenWhen:
        if self.unlock_on is not None and self.unlock_day is not None:
            raise ValueError(
                f"Open When {self.id!r} sets both 'unlock_on' and 'unlock_day'. "
                "Use one, or neither for immediate availability."
            )
        return self

    def unlocks_on(self, enlistment: date) -> date | None:
        """The date this becomes available, or None if always available."""
        if self.unlock_on is not None:
            return self.unlock_on
        if self.unlock_day is not None:
            return enlistment + timedelta(days=self.unlock_day)
        return None

    def is_unlocked(self, today: date, enlistment: date) -> bool:
        unlock = self.unlocks_on(enlistment)
        return unlock is None or unlock <= today
