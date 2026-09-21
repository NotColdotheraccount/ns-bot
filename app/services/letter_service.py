"""Delivers letters you wrote before leaving.

## Why this fails differently from the morning message

The morning job uses misfire_grace_time: if the bot was down at 08:00, that
day's greeting is skipped. Correct — a "good morning" at 4pm is worse than none.

A letter is the opposite. It is a specific thing you wrote, meant to arrive
once. If the bot was down for three days, those letters should still arrive,
because skipping one means she never receives it at all.

So letters are not scheduled as individual jobs. A single dispatcher runs daily,
asks "what is due and not yet sent", and delivers it. That design means:

  * a missed day is caught up automatically on the next run
  * restarting mid-send cannot duplicate anything
  * you can see exactly what is pending with a SQL query
  * adding a letter later needs no scheduling code at all

## The burst guard

If the bot is offline for two weeks, the catch-up would deliver every missed
letter at once. MAX_PER_RUN caps a single run so she gets them over several
days instead of a wall of text. The rest stay pending and arrive on the next
run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from app.content.letter_library import LetterLibrary
from app.content.letter_schema import Letter
from app.database.repositories.letters import LetterRepository
from app.database.repositories.settings import SettingsRepository
from app.database.session import Database
from app.features import Feature
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)

ENLISTMENT_KEY = "enlistment_date"
DEFAULT_ENLISTMENT = "2026-10-01"

# Most letters delivered in one dispatcher run, so a long outage does not
# produce a wall of text.
MAX_PER_RUN = 2


class LetterService:
    """Chooses which letters are due and sends them, exactly once each."""

    def __init__(
        self,
        *,
        library: LetterLibrary,
        database: Database,
        topic_service: TopicService,
        timezone: ZoneInfo,
        group_id: int,
    ) -> None:
        self._library = library
        self._db = database
        self._topics = topic_service
        self._tz = timezone
        self._group_id = group_id

    # ------------------------------------------------------------- settings

    async def enlistment_date(self) -> date:
        async with self._db.session() as session:
            raw = await SettingsRepository(session).get(ENLISTMENT_KEY, DEFAULT_ENLISTMENT)
        try:
            return date.fromisoformat(raw)
        except ValueError:
            logger.error("Invalid enlistment date stored: %r — using default.", raw)
            return date.fromisoformat(DEFAULT_ENLISTMENT)

    async def set_enlistment_date(self, value: date) -> None:
        async with self._db.session() as session:
            await SettingsRepository(session).set(ENLISTMENT_KEY, value.isoformat())
        logger.info("Enlistment date set | date=%s", value.isoformat())

    def today(self) -> date:
        """Today in Singapore, not in the server's timezone."""
        return datetime.now(self._tz).date()

    # ------------------------------------------------------------- dispatch

    async def pending(self) -> list[Letter]:
        """Letters that are due but have not been delivered."""
        enlistment = await self.enlistment_date()
        due = self._library.due(self.today(), enlistment)

        async with self._db.session() as session:
            already = await LetterRepository(session).sent_ids()

        return [letter for letter in due if letter.id not in already]

    async def dispatch_due(self, bot: Bot) -> int:
        """Send up to MAX_PER_RUN pending letters. Returns how many were sent."""
        thread_id = self._topics.thread_for(Feature.LETTERS)
        if thread_id is None:
            logger.warning("Skipping letters — feature not bound to a topic.")
            return 0

        pending = await self.pending()
        if not pending:
            return 0

        sent = 0
        for letter in pending[:MAX_PER_RUN]:
            # Claim the letter BEFORE sending. If the send fails we release it
            # again below. Claiming first means two dispatcher runs overlapping
            # cannot both pick up the same letter.
            async with self._db.session() as session:
                claimed = await LetterRepository(session).mark_sent(letter.id, letter.number)
            if not claimed:
                continue

            # Catch *everything*, not just TelegramAPIError. A letter is
            # claimed before sending, so any escaping exception would leave it
            # marked as delivered while she never received it — the one failure
            # this feature cannot have. Network errors, disk errors and bugs all
            # have to release the claim.
            try:
                ok = await self.send(bot, letter, thread_id=thread_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unexpected error sending letter | number=%s error=%s",
                    letter.number,
                    type(exc).__name__,
                )
                ok = False

            if ok:
                sent += 1
                logger.info("Letter delivered | number=%s", letter.number)
            else:
                async with self._db.session() as session:
                    await LetterRepository(session).unmark(letter.id)
                logger.error("Letter send failed, released | number=%s", letter.number)

            if sent:
                await asyncio.sleep(2)

        return sent

    # ---------------------------------------------------------------- sending

    async def send(self, bot: Bot, letter: Letter, *, thread_id: int) -> bool:
        """Render one letter. Returns True if the text was delivered."""
        try:
            await bot.send_message(
                chat_id=self._group_id,
                message_thread_id=thread_id,
                text=self._format(letter),
            )

            photo = self._library.resolve(letter.photo)
            if photo is not None:
                await bot.send_photo(
                    chat_id=self._group_id,
                    message_thread_id=thread_id,
                    photo=FSInputFile(photo),
                )

            video = self._library.resolve(letter.video)
            if video is not None:
                await bot.send_video(
                    chat_id=self._group_id,
                    message_thread_id=thread_id,
                    video=FSInputFile(video),
                )

            voice = self._library.resolve(letter.voice)
            if voice is not None:
                await asyncio.sleep(1.0)
                await bot.send_voice(
                    chat_id=self._group_id,
                    message_thread_id=thread_id,
                    voice=FSInputFile(voice),
                )

            return True

        except TelegramAPIError as exc:
            logger.error(
                "Letter send failed | number=%s error=%s", letter.number, type(exc).__name__
            )
            return False

    @staticmethod
    def _format(letter: Letter) -> str:
        """Telegram caps a message at 4096 characters."""
        text = f"💌 <b>Letter #{letter.number} — {letter.title}</b>\n\n{letter.body}"
        if len(text) > 4096:
            text = text[:4090].rstrip() + "…"
        return text

    # ----------------------------------------------------------------- admin

    def by_number(self, number: int) -> Letter | None:
        return self._library.by_number(number)

    def upcoming(self, today: date, enlistment: date, limit: int = 5) -> list[Letter]:
        return self._library.upcoming(today, enlistment, limit)

    @property
    def count(self) -> int:
        return self._library.count

    async def delivered_count(self) -> int:
        async with self._db.session() as session:
            return len(await LetterRepository(session).sent_ids())
