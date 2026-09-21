"""The shape of a memory.

A memory is deliberately NOT a ContentItem. ContentItem is one thing you send:
a message, a recording, a photo. A memory is a small story — a title, a date, a
caption, several photos, sometimes a video or a voice note explaining it.

Forcing that into ContentItem would have meant adding five optional fields that
are null for every other kind of content, which is how schemas rot. Two models
is the honest representation.

What they *do* share is the send-history table: both are tracked in
ContentState keyed on their string id, so the same anti-repetition logic works
for both without either knowing about the other. Note the id prefixes below —
`mem_` vs `voice_` — which keep the two id spaces from ever colliding.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Memory(BaseModel):
    """One shared memory, possibly with several photos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)

    # Her-facing number, used by "memory 17" and /memory 17. Separate from `id`
    # on purpose: ids must never be reused, but you may want to renumber how
    # they are presented without breaking send history.
    number: int = Field(gt=0)

    title: str = Field(min_length=1, max_length=200)

    # Free text, not a date type: "sometime in June", "our second date" and
    # "2025-03-14" are all things you might want to write, and only one of them
    # parses. Nothing sorts or filters on this, so a string is the right call.
    date: str | None = None
    location: str | None = None

    description: str | None = None

    # Paths relative to media/, e.g. "photos/first_date_01.jpg".
    photos: tuple[str, ...] = ()
    videos: tuple[str, ...] = ()
    voice: str | None = None

    tags: tuple[str, ...] = ()
    mood: str | None = None

    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    enabled: bool = True

    @field_validator("tags", "photos", "videos", mode="before")
    @classmethod
    def _to_tuple(cls, value: object) -> object:
        """Accept a single string or a list; always store a tuple."""
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for tag in value:
            seen.setdefault(str(tag).strip().lower(), None)
        return tuple(seen)

    @field_validator("photos")
    @classmethod
    def _check_album_size(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # Telegram media groups accept a maximum of 10 items. Catching this at
        # load time gives a clear error instead of a runtime API rejection.
        if len(value) > 10:
            raise ValueError(
                f"A memory can have at most 10 photos (Telegram album limit); got {len(value)}."
            )
        return value

    def has_tag(self, tag: str) -> bool:
        return tag.strip().lower() in self.tags

    def matches_any_tag(self, tags: tuple[str, ...]) -> bool:
        if not tags:
            return True
        return any(self.has_tag(tag) for tag in tags)

    @property
    def has_media(self) -> bool:
        return bool(self.photos or self.videos or self.voice)
