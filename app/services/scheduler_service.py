"""Scheduled messages: good morning, goodnight, daily check-in.

## Why jobs are rebuilt at every startup

APScheduler can persist jobs to a database, and for this project that is a trap.
A persisted job stores a reference to the function that runs it; change or move
that function and the stored job either fails to load or silently runs stale
behaviour. Schedules here are three cron entries derived from settings, so
rebuilding them on boot costs nothing and cannot go stale.

Anything that genuinely must survive a restart — which letter has been sent,
what she answered — lives in SQLite as data, not as a pickled job.

## The destination guard

Every scheduled send resolves its destination through TopicService. If a
feature is not bound to a topic, the job **does not send**. It never falls back
to the General topic.

That guard matters more than it looks. `send_message` with `message_thread_id=None`
is a perfectly valid call that posts to General — so a missing binding would not
raise an error, it would quietly post your goodnight message to the wrong room
every night.

## Timezone

All cron triggers are constructed with the configured timezone attached. A cron
trigger with no timezone uses the *machine's* local time, which on a hosting
provider is UTC — an 08:00 morning message would arrive at 16:00 Singapore time.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.content.schema import ContentKind
from app.database.repositories.settings import SettingsRepository
from app.database.session import Database
from app.features import Feature
from app.keyboards.checkin import checkin_keyboard
from app.services.content_selector import ContentSelector
from app.services.media_service import MediaService
from app.services.ops_service import OpsService
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)

# Setting keys and their defaults, in 24-hour HH:MM Singapore time.
SCHEDULE_DEFAULTS: dict[str, str] = {
    "schedule.morning": "06:00",
    "schedule.checkin": "19:00",
    "schedule.goodnight": "22:00",
    "schedule.letters": "10:00",
}

_CHECKIN_PROMPTS = (
    "hi baby how was your day today?",
    "how was your day today baby?",
    "just checking in",
    "hiii babyyy how are you doing?",
    "how are you feeling today baby?",
    "how did today go for you?",
    "hiii baby just wanted to check on you",
    "how has your day been babyyy?",
    "you doing okay baby?",
    "how are you babyyyy?",
    "tell me about your dayyy",
    "what did you do today babyyy?",
    "how was everything today?",
    "hiii cutieee how was your day?",
    "babyyyy how are you feelingggg?",
    "just checking up on you babyyy",
    "how is my babyyyy doing?",
    "did you have a good day today?",
    "anything interesting happen today babyyy?",
    "how did your day treat you today?",
    "helloooo babyyy how have you been today?",
    "hiii princessss how was today?",
    "how are things going babyyyy?",
    "hope your day was okayyy, how was it?",
    "babyyyy tell me how your day wenttt",
    "how was everything going today cutieee?",
    "you okayyyy babyyy?",
    "just wanted to know how you are doinggg",
    "how was your morning and afternoon babyyy?",
    "what was the best part of your day today?",
    "did anything make you happy today babyyy?",
    "was today tiringggg?",
    "how are you feeling right now babyyy?",
)

# Chance a scheduled text is followed by a real voice note.
VOICE_CHANCE = 0.45


def parse_hhmm(value: str) -> tuple[int, int] | None:
    """Parse 'HH:MM' into (hour, minute), or None if malformed."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


class SchedulerService:
    """Owns the APScheduler instance and the scheduled sends."""

    def __init__(
        self,
        *,
        bot: Bot,
        database: Database,
        topic_service: TopicService,
        selector: ContentSelector,
        media: MediaService,
        timezone: ZoneInfo,
        group_id: int,
        letter_service=None,
        ops: OpsService | None = None,
    ) -> None:
        self._bot = bot
        self._db = database
        self._topics = topic_service
        self._selector = selector
        self._media = media
        self._tz = timezone
        self._group_id = group_id
        self._letters = letter_service
        self._ops = ops
        self._scheduler = AsyncIOScheduler(timezone=timezone)

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        await self.reload_jobs()
        self._add_maintenance_jobs()
        self._scheduler.start()
        logger.info("Scheduler started | tz=%s", self._tz.key)
        for job in self._scheduler.get_jobs():
            logger.info("  job %-10s next run: %s", job.id, job.next_run_time)

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    async def reload_jobs(self) -> None:
        """Rebuild every cron job from current settings."""
        async with self._db.session() as session:
            repo = SettingsRepository(session)
            times = {
                key: await repo.get(key, default)
                for key, default in SCHEDULE_DEFAULTS.items()
            }

        jobs = (
            ("morning", times["schedule.morning"], self.send_morning),
            ("checkin", times["schedule.checkin"], self.send_checkin),
            ("goodnight", times["schedule.goodnight"], self.send_goodnight),
            ("letters", times["schedule.letters"], self.send_letters),
        )

        for job_id, value, callback in jobs:
            parsed = parse_hhmm(value)
            if parsed is None:
                logger.error("Invalid schedule for %s: %r — job not scheduled.", job_id, value)
                continue
            hour, minute = parsed
            self._scheduler.add_job(
                callback,
                CronTrigger(hour=hour, minute=minute, timezone=self._tz),
                id=job_id,
                # Replace rather than duplicate when /setschedule triggers a reload.
                replace_existing=True,
                # If the bot was down at the scheduled moment, do not fire late.
                # A "good morning" arriving at 2pm because of a redeploy is worse
                # than no message at all.
                misfire_grace_time=600,
                coalesce=True,
            )

    def _add_maintenance_jobs(self) -> None:
        """Fixed-time ops jobs. Not user-configurable, so not in settings."""
        if self._ops is None:
            return
        self._scheduler.add_job(
            self.send_heartbeat,
            CronTrigger(hour=12, minute=0, timezone=self._tz),
            id="heartbeat",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        self._scheduler.add_job(
            self.send_backup,
            # Sunday 03:00 Singapore — nobody is using the bot.
            CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=self._tz),
            id="backup",
            replace_existing=True,
            # A backup is still worth taking late, unlike a greeting.
            misfire_grace_time=6 * 3600,
            coalesce=True,
        )

    async def send_heartbeat(self) -> None:
        if self._ops is None:
            return
        extra = ""
        if self._letters is not None:
            try:
                pending = len(await self._letters.pending())
                delivered = await self._letters.delivered_count()
                extra = f"letters: {delivered} delivered · {pending} pending"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Heartbeat stats failed | error=%s", type(exc).__name__)
        await self._ops.send_heartbeat(self._bot, extra)

    async def send_backup(self) -> None:
        if self._ops is not None:
            await self._ops.send_backup(self._bot)

    async def current_schedule(self) -> dict[str, str]:
        async with self._db.session() as session:
            repo = SettingsRepository(session)
            return {
                key.split(".", 1)[1]: await repo.get(key, default)
                for key, default in SCHEDULE_DEFAULTS.items()
            }

    # ------------------------------------------------------------------- jobs

    async def send_morning(self) -> None:
        await self._send_tagged(
            Feature.GOOD_MORNING, tags=("morning", "love", "general"), action="morning"
        )

    async def send_goodnight(self) -> None:
        await self._send_tagged(
            Feature.GOODNIGHT, tags=("goodnight", "sleep", "love"), action="goodnight"
        )

    async def send_letters(self) -> None:
        """Daily letter dispatcher.

        Unlike the greeting jobs, this one is safe to miss: a letter that was
        due yesterday is still pending today and goes out on the next run.
        """
        if self._letters is None:
            return
        try:
            count = await self._letters.dispatch_due(self._bot)
            if count:
                logger.info("Scheduled send OK | job=letters count=%d", count)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduled send failed | job=letters error=%s", type(exc).__name__)

    async def send_checkin(self) -> None:
        """Post the daily check-in prompt with mood buttons."""
        thread_id = self._destination(Feature.DAILY_CHECKIN, "checkin")
        if thread_id is None:
            return

        try:
            await self._bot.send_message(
                chat_id=self._group_id,
                message_thread_id=thread_id,
                text=random.choice(_CHECKIN_PROMPTS),
                reply_markup=checkin_keyboard(self.local_date()),
            )
            logger.info("Scheduled send OK | job=checkin")
        except Exception as exc:  # noqa: BLE001
            # One failed job must never stop the scheduler. APScheduler would
            # otherwise log a traceback and continue, but this keeps the log
            # clean and free of message content.
            logger.error("Scheduled send failed | job=checkin error=%s", type(exc).__name__)

    # -------------------------------------------------------------- internals

    async def _send_tagged(
        self, feature: Feature, *, tags: tuple[str, ...], action: str
    ) -> None:
        """Send a written message for a feature, sometimes with a voice note."""
        thread_id = self._destination(feature, action)
        if thread_id is None:
            return

        chat_id = self._group_id

        try:
            item = await self._selector.choose(kinds=(ContentKind.TEXT,), tags=tags)
            if item is None:
                logger.warning("No content for scheduled job | job=%s", action)
                return

            sent = await self._media.send(
                self._bot, item, chat_id=chat_id, thread_id=thread_id
            )
            if not sent:
                return
            await self._selector.record_sent(item, user_id=0, feature=feature.value)

            if random.random() <= VOICE_CHANCE:
                voice = await self._selector.choose(kinds=(ContentKind.VOICE,), tags=tags)
                if voice is not None:
                    ok = await self._media.send(
                        self._bot, voice, chat_id=chat_id, thread_id=thread_id
                    )
                    if ok:
                        await self._selector.record_sent(
                            voice, user_id=0, feature=feature.value
                        )

            logger.info("Scheduled send OK | job=%s", action)

        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduled send failed | job=%s error=%s", action, type(exc).__name__)

    def _destination(self, feature: Feature, job: str) -> int | None:
        """Resolve the thread to post into, or None if unbound.

        Returning None rather than falling back is the whole point: an unbound
        feature must stay silent, not post into General.
        """
        thread_id = self._topics.thread_for(feature)
        if thread_id is None:
            logger.warning(
                "Skipping scheduled job — feature not bound to a topic | job=%s feature=%s",
                job,
                feature.value,
            )
        return thread_id

    def local_date(self) -> str:
        """Today's date in the configured timezone, as YYYY-MM-DD."""
        return datetime.now(self._tz).strftime("%Y-%m-%d")

    async def set_schedule(self, name: str, value: str) -> None:
        """Persist a new time and rebuild jobs immediately."""
        async with self._db.session() as session:
            await SettingsRepository(session).set(f"schedule.{name}", value)
        await self.reload_jobs()
        logger.info("Schedule updated | job=%s time=%s", name, value)

    def next_runs(self) -> list[tuple[str, datetime | None]]:
        """(job id, next fire time) for every job, soonest first."""
        jobs = [(job.id, job.next_run_time) for job in self._scheduler.get_jobs()]
        far_future = datetime.max.replace(tzinfo=self._tz)
        return sorted(jobs, key=lambda item: item[1] or far_future)

    def thread_for(self, feature: Feature) -> int | None:
        """Destination thread for a feature, for admin display."""
        return self._topics.thread_for(feature)
