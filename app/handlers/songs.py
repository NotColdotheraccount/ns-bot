"""#SongsForYou — recordings of you singing."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.content.schema import ContentKind
from app.features import Feature
from app.filters.topic import BoundTo
from app.intents import extract_mood
from app.services.delivery import ContentDelivery

logger = logging.getLogger(__name__)

router = Router(name="songs")


@router.message(BoundTo(Feature.SONGS), F.text)
async def handle_songs(message: Message, bot: Bot, delivery: ContentDelivery) -> None:
    """Send a song, optionally filtered by requested mood."""
    mood = extract_mood(message.text or "")
    tags = (mood,) if mood else ()

    await delivery.typing(bot, message, action="upload_voice")

    item = await delivery.deliver_one(
        bot, message, feature=Feature.SONGS, kinds=(ContentKind.AUDIO,), tags=tags
    )
    if item is not None:
        return

    if mood:
        item = await delivery.deliver_one(
            bot, message, feature=Feature.SONGS, kinds=(ContentKind.AUDIO,)
        )
        if item is not None:
            return

    await message.answer("no songs recorded yet 🎵")
