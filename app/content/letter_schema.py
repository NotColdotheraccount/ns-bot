"""The shape of a letter you wrote before leaving.

A letter is not content in the ContentItem sense. ContentItem is drawn at
random on request; a letter is a specific thing that arrives once, on a
specific day, in an order you chose. Different lifecycle, different model.

Two ways to schedule one:

  day: 14          -> fourteen days after your enlistment date
  send_on: "2027-02-14"  -> an exact calendar date

`day` is usually what you want. It survives a change of enlistment date, and
"day 30" is how NS time actually gets counted. `send_on` is for things tied to
the calendar rather than to your service — her birthday, your anniversary.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Letter(BaseModel):
    """One letter, delivered once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    number: int = Field(gt=0)

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)

    # Exactly one of these must be set.
    day: int | None = Field(default=None, ge=0)
    send_on: date | None = None

    # Paths relative to media/.
    photo: str | None = None
    voice: str | None = None
    video: str | None = None

    enabled: bool = True

    @model_validator(mode="after")
    def _check_schedule(self) -> Letter:
        if (self.day is None) == (self.send_on is None):
            raise ValueError(
                f"Letter {self.id!r} must set exactly one of 'day' "
                "(days after enlistment) or 'send_on' (a calendar date)."
            )
        return self

    def due_on(self, enlistment: date) -> date:
        """The calendar date this letter should arrive."""
        if self.send_on is not None:
            return self.send_on
        from datetime import timedelta

        return enlistment + timedelta(days=self.day or 0)

    def is_due(self, today: date, enlistment: date) -> bool:
        return self.due_on(enlistment) <= today
