"""Selects and sends memories.

## Telegram albums

Several photos sent individually arrive as several separate messages, which
looks like spam. `send_media_group` bundles 2-10 into one swipeable album.

Two rules the API enforces and this code respects:
  * 2-10 items. One photo must use send_photo instead.
  * The caption goes on the FIRST item only. Put it on all of them and Telegram
    either rejects the call or renders it strangely.

Albums are not file_id cached in this version. Caching would mean tracking a
separate id per photo inside a memory, and memories are viewed far less often
than voice notes are. Worth revisiting only if album sends feel slow.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from app.content.memory_library import MemoryLibrary
from app.content.memory_schema import Memory
from app.database.repositories.content import ContentRepository
from app.database.session import Database
from app.services.scoring import DEFAULT_COOLDOWN, weighted_pick

logger = logging.getLogger(__name__)

MAX_ALBUM_SIZE = 10


class MemoryService:
    """Picks a memory and renders it into Telegram messages."""

    def __init__(
        self,
        library: MemoryLibrary,
        database: Database,
        cooldown: timedelta = DEFAULT_COOLDOWN,
        rng: random.Random | None = None,
    ) -> None:
        self._library = library
        self._db = database
        self._cooldown = cooldown
        self._rng = rng or random.Random()

    # -------------------------------------------------------------- selection

    def by_number(self, number: int) -> Memory | None:
        """Look up a memory by its her-facing number."""
        return self._library.by_number(number)

    @property
    def count(self) -> int:
        return self._library.count

    async def choose(self, *, tags: tuple[str, ...] = ()) -> Memory | None:
        """Pick a memory, preferring ones she has not seen recently."""
        candidates = self._library.select(tags=tags)
        if not candidates:
            return None

        async with self._db.session() as session:
            states = await ContentRepository(session).states_for(
                [memory.id for memory in candidates]
            )

        return weighted_pick(candidates, states, rng=self._rng, cooldown=self._cooldown)

    # ---------------------------------------------------------------- sending

    async def send(
        self, bot: Bot, memory: Memory, *, chat_id: int, thread_id: int | None
    ) -> bool:
        """Render one memory. Returns True if anything was delivered."""
        delivered = False

        photos = self._library.existing_files(memory.photos)
        caption = self._caption(memory)

        try:
            if len(photos) >= 2:
                delivered = await self._send_album(
                    bot, photos, caption, chat_id=chat_id, thread_id=thread_id
                )
            elif len(photos) == 1:
                await bot.send_photo(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    photo=FSInputFile(photos[0]),
                    caption=caption,
                )
                delivered = True
            else:
                # No photos available — the words are still worth sending.
                await bot.send_message(
                    chat_id=chat_id, message_thread_id=thread_id, text=caption
                )
                delivered = True

            for relative in memory.videos:
                path = self._library.resolve(relative)
                if path is not None:
                    await bot.send_video(
                        chat_id=chat_id,
                        message_thread_id=thread_id,
                        video=FSInputFile(path),
                    )

            voice_path = self._library.resolve(memory.voice)
            if voice_path is not None:
                await asyncio.sleep(0.8)
                await bot.send_voice(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    voice=FSInputFile(voice_path),
                )

        except TelegramAPIError as exc:
            logger.error(
                "Memory send failed | id=%s error=%s", memory.id, type(exc).__name__
            )
            return delivered

        return delivered

    async def _send_album(
        self,
        bot: Bot,
        photos: list,
        caption: str,
        *,
        chat_id: int,
        thread_id: int | None,
    ) -> bool:
        """Send up to 10 photos as one swipeable album."""
        media = [
            InputMediaPhoto(
                media=FSInputFile(path),
                # Caption on the first item only — Telegram's rule.
                caption=caption if index == 0 else None,
            )
            for index, path in enumerate(photos[:MAX_ALBUM_SIZE])
        ]
        await bot.send_media_group(
            chat_id=chat_id, message_thread_id=thread_id, media=media
        )
        return True

    # ------------------------------------------------------------- formatting

    @staticmethod
    def _caption(memory: Memory) -> str:
        """Build the caption. Telegram caps captions at 1024 characters."""
        lines = [f"<b>#{memory.number} — {memory.title}</b>"]

        meta = " · ".join(part for part in (memory.date, memory.location) if part)
        if meta:
            lines.append(f"<i>{meta}</i>")

        if memory.description:
            lines.append("")
            lines.append(memory.description)

        caption = "\n".join(lines)
        if len(caption) > 1024:
            caption = caption[:1020].rstrip() + "…"
        return caption

    async def record_sent(self, memory: Memory, *, user_id: int, feature: str) -> None:
        """Mark as sent. Only called after Telegram accepted the send."""
        async with self._db.session() as session:
            await ContentRepository(session).record_send(
                content_id=memory.id, user_id=user_id, feature=feature
            )
