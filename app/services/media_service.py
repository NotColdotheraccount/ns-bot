"""Sends content to Telegram as the correct message type.

Two jobs:

1. **Dispatch by kind.** A voice note, a song, a photo and a video are four
   different Telegram API calls with four different response shapes. Handlers
   should not care — they hand over a ContentItem and this figures it out.

2. **Cache file_id.** The first time a file is sent, Telegram uploads it and
   returns a `file_id`. Every later send can pass that string instead of the
   bytes, so Telegram serves its own copy. A 4 MB song goes from a multi-second
   upload to an instant send. On a small hosting plan with limited bandwidth
   this is the difference between the bot feeling snappy and feeling broken.

file_id values are specific to one bot token. If you ever regenerate the token,
the cached ids become invalid — which is handled below by falling back to a
fresh upload rather than failing the send.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, Message

from app.content.library import ContentLibrary
from app.content.schema import ContentItem, ContentKind
from app.database.repositories.content import ContentRepository
from app.database.session import Database

logger = logging.getLogger(__name__)


class MediaService:
    """Delivers a ContentItem to a Telegram chat or forum topic."""

    def __init__(self, library: ContentLibrary, database: Database) -> None:
        self._library = library
        self._db = database

    async def send(
        self,
        bot: Bot,
        item: ContentItem,
        *,
        chat_id: int,
        thread_id: int | None = None,
        caption: str | None = None,
    ) -> bool:
        """Send one item. Returns True on success.

        Never raises on a Telegram error: one failed voice note should not take
        down a scheduled job or leave her with no reply at all.
        """
        try:
            if item.kind is ContentKind.TEXT:
                await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=item.text or "",
                )
                return True

            return await self._send_media(
                bot, item, chat_id=chat_id, thread_id=thread_id, caption=caption
            )

        except TelegramAPIError as exc:
            # Log the item id and error type, never the content itself.
            logger.error(
                "Telegram send failed | content_id=%s kind=%s error=%s",
                item.id,
                item.kind.value,
                type(exc).__name__,
            )
            return False

    # --------------------------------------------------------------- internal

    async def _send_media(
        self,
        bot: Bot,
        item: ContentItem,
        *,
        chat_id: int,
        thread_id: int | None,
        caption: str | None,
    ) -> bool:
        cached_id = await self._cached_file_id(item.id)

        if cached_id is not None:
            message = await self._dispatch(
                bot, item, cached_id, chat_id, thread_id, caption
            )
            if message is not None:
                return True
            # The cached id was rejected — stale, or the token changed. Fall
            # through and upload the real file again.
            logger.info("Cached file_id rejected, re-uploading | id=%s", item.id)

        path = self._library.resolve_file(item)
        if path is None or not path.exists():
            logger.error("Media file missing at send time | id=%s file=%s", item.id, item.file)
            return False

        message = await self._dispatch(
            bot, item, FSInputFile(path), chat_id, thread_id, caption
        )
        if message is None:
            return False

        file_id = self._extract_file_id(message, item.kind)
        if file_id:
            await self._store_file_id(item.id, file_id)
        return True

    async def _dispatch(
        self,
        bot: Bot,
        item: ContentItem,
        payload: str | FSInputFile,
        chat_id: int,
        thread_id: int | None,
        caption: str | None,
    ) -> Message | None:
        """Call the right send_* method. Returns None if Telegram rejected it."""
        text = caption or item.caption
        common = {"chat_id": chat_id, "message_thread_id": thread_id}

        try:
            match item.kind:
                case ContentKind.VOICE:
                    # Voice notes render as the round waveform bubble. Telegram
                    # requires OGG/Opus here; an mp3 will be rejected.
                    return await bot.send_voice(**common, voice=payload, caption=text)
                case ContentKind.AUDIO:
                    # Audio renders as a music player with title and performer.
                    return await bot.send_audio(
                        **common, audio=payload, caption=text, title=item.title
                    )
                case ContentKind.PHOTO:
                    return await bot.send_photo(**common, photo=payload, caption=text)
                case ContentKind.VIDEO:
                    return await bot.send_video(**common, video=payload, caption=text)
                case _:
                    logger.error("Unsendable kind | id=%s kind=%s", item.id, item.kind)
                    return None
        except TelegramAPIError as exc:
            logger.warning(
                "Send attempt failed | id=%s kind=%s error=%s",
                item.id,
                item.kind.value,
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _extract_file_id(message: Message, kind: ContentKind) -> str | None:
        """Pull the reusable file_id out of Telegram's response."""
        match kind:
            case ContentKind.VOICE:
                return message.voice.file_id if message.voice else None
            case ContentKind.AUDIO:
                return message.audio.file_id if message.audio else None
            case ContentKind.PHOTO:
                # Telegram returns several resolutions; the last is the largest.
                return message.photo[-1].file_id if message.photo else None
            case ContentKind.VIDEO:
                return message.video.file_id if message.video else None
            case _:
                return None

    async def _cached_file_id(self, content_id: str) -> str | None:
        async with self._db.session() as session:
            states = await ContentRepository(session).states_for([content_id])
        state = states.get(content_id)
        return state.telegram_file_id if state else None

    async def _store_file_id(self, content_id: str, file_id: str) -> None:
        async with self._db.session() as session:
            await ContentRepository(session).cache_file_id(content_id, file_id)
        logger.debug("Cached file_id | id=%s", content_id)
