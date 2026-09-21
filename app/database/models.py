"""ORM models.

Stage 3 defines only what the topic system needs. Stage 4 expands this file
with content, memories, check-ins and the rest.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, utcnow


class TopicBinding(Base, TimestampMixin):
    """Links one Telegram forum topic to one feature.

    The pair (group_id, message_thread_id) is unique: a topic can own at most
    one feature. The reverse is deliberately *not* enforced — you may want two
    topics bound to the same feature later, and nothing in the design breaks
    if you do.
    """

    __tablename__ = "topic_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # BigInteger because Telegram supergroup IDs (-100...) exceed 32 bits.
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_thread_id: Mapped[int] = mapped_column(nullable=False)

    # Stored as a plain string rather than a SQL enum so that adding a feature
    # to the Feature enum never requires a schema migration.
    feature: Mapped[str] = mapped_column(String(64), nullable=False)

    # Cosmetic only, captured at bind time to make /bindings readable. Never
    # used to resolve a feature.
    topic_title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    bound_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("group_id", "message_thread_id", name="uq_binding_topic"),
        Index("ix_binding_feature", "feature"),
    )

    def __repr__(self) -> str:
        return (
            f"<TopicBinding thread={self.message_thread_id} feature={self.feature!r}>"
        )


class ContentState(Base):
    """Runtime counters for one authored content item.

    Deliberately separate from the YAML that defines the item. You can rewrite,
    reorder or reformat your content files at any time without losing the
    history that keeps the bot from repeating itself — the two are joined on the
    stable string id you write by hand (voice_004, not an autoincrement).
    """

    __tablename__ = "content_state"

    content_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    times_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Telegram returns a file_id after the first upload. Reusing it on later
    # sends skips re-uploading the file entirely, which matters for a 20 MB
    # video on a small hosting plan.
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def __repr__(self) -> str:
        return f"<ContentState {self.content_id} sent={self.times_sent}>"


class ContentHistory(Base, TimestampMixin):
    """An append-only log of what was sent, to whom.

    ContentState answers 'how often'. This answers 'in what order', which is
    what /content recent uses and what a future 'you already saw this today'
    check would need.
    """

    __tablename__ = "content_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    feature: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_history_content", "content_id"),
        Index("ix_history_created", "created_at"),
    )


class BotSetting(Base):
    """Key-value settings that must be changeable at runtime.

    Schedule times live here rather than in .env because you should be able to
    change them from Telegram during bookout, without a redeploy. Anything that
    is a secret or must exist before the bot can start stays in .env; anything
    you might reasonably want to tweak later lives here.
    """

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CheckIn(Base, TimestampMixin):
    """Her answer to the daily 'how was your day' prompt.

    local_date is the Asia/Singapore calendar date as a string, and is unique.
    Storing the local date rather than deriving it from created_at means "one
    check-in per day" means *her* day, not a UTC day that rolls over at 8am
    Singapore time.
    """

    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    local_date: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    mood: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (Index("ix_checkin_date", "local_date"),)

    def __repr__(self) -> str:
        return f"<CheckIn {self.local_date} {self.mood}>"


class LetterState(Base):
    """Record that a letter has been delivered.

    The existence of a row IS the 'already sent' flag. A letter must arrive
    exactly once: a redeploy, a crash mid-send, or two dispatcher runs in the
    same day must never produce a duplicate. Because letter_id is the primary
    key, a second insert fails rather than silently duplicating — the database
    enforces it, not application logic that could be bypassed later.
    """

    __tablename__ = "letter_state"

    letter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return f"<LetterState #{self.number} sent={self.sent_at}>"
