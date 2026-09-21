"""Declarative base shared by every ORM model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp.

    Everything is stored in UTC and converted to Asia/Singapore only at display
    time. Storing local time in a database is a reliable way to produce bugs the
    moment a server runs in a different region or a DST boundary is crossed.
    Singapore has no DST, but the hosting provider is not guaranteed to be here.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""


class TimestampMixin:
    """Adds a created_at column to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
