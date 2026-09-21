"""The shape of authored content.

Everything in this file describes content *you* write: a reassurance message, a
voice recording, a song. It is validated with pydantic at load time so a typo in
a YAML file becomes a clear startup error rather than a crash at 08:00 when a
scheduled job fires.

Nothing here records runtime state. How often an item has been sent lives in
SQLite (see app/database/models.py). The split matters: you can edit, reorder
and redeploy your YAML files freely without ever losing send history.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContentKind(StrEnum):
    """How an item should be delivered to Telegram."""

    TEXT = "text"
    VOICE = "voice"      # sent as a Telegram voice note (waveform bubble)
    AUDIO = "audio"      # sent as a music file — used for songs
    PHOTO = "photo"
    VIDEO = "video"

    @property
    def needs_file(self) -> bool:
        """True for kinds that must reference a media file."""
        return self is not ContentKind.TEXT


class ContentItem(BaseModel):
    """One piece of content you authored."""

    # forbid extra keys: a mistyped YAML field should be an error, not silently
    # ignored. Silently-ignored config is a genuinely nasty class of bug.
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    kind: ContentKind

    text: str | None = None
    file: str | None = None

    title: str | None = None
    description: str | None = None
    caption: str | None = None

    tags: tuple[str, ...] = ()
    mood: str | None = None

    # Relative likelihood of being chosen. 2.0 is roughly twice as likely as
    # 1.0, before recency and usage adjustments are applied.
    weight: float = Field(default=1.0, gt=0.0, le=10.0)
    enabled: bool = True

    @field_validator("tags", mode="before")
    @classmethod
    def _normalise_tags(cls, value: object) -> object:
        """Lowercase and de-duplicate tags, preserving order.

        Means 'Missing_Me' in one file and 'missing_me' in another still match.
        """
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple)):
            seen: dict[str, None] = {}
            for tag in value:
                seen.setdefault(str(tag).strip().lower(), None)
            return tuple(seen)
        return value

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"Content id {value!r} may only contain letters, digits, "
                "underscores and hyphens."
            )
        return cleaned

    @model_validator(mode="after")
    def _check_payload(self) -> ContentItem:
        """Ensure the item actually carries something sendable."""
        if self.kind is ContentKind.TEXT:
            if not (self.text and self.text.strip()):
                raise ValueError(f"Content {self.id!r} is kind 'text' but has no text.")
        elif not (self.file and self.file.strip()):
            raise ValueError(
                f"Content {self.id!r} is kind {self.kind.value!r} and needs a 'file'."
            )
        return self

    def has_tag(self, tag: str) -> bool:
        return tag.strip().lower() in self.tags

    def matches_any_tag(self, tags: tuple[str, ...]) -> bool:
        """True if the item carries at least one of the given tags."""
        if not tags:
            return True
        return any(self.has_tag(tag) for tag in tags)
