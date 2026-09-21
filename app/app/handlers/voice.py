"""#HearMyVoice — real recordings, nothing generated."""

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

router = Router(name="voice")


@router.message(BoundTo(Feature.VOICE), F.text)
async def handle_voice(message: Message, bot: Bot, delivery: ContentDelivery) -> None:
    """Send a voice recording, optionally filtered by a requested mood."""
    mood = extract_mood(message.text or "")
    tags = (mood,) if mood else ()

    await delivery.typing(bot, message, action="record_voice")

    item = await delivery.deliver_one(
        bot, message, feature=Feature.VOICE, kinds=(ContentKind.VOICE,), tags=tags
    )

    if item is not None:
        return

    # Nothing matched. If a mood filter was applied, retry without it before
    # giving up — a narrower request should degrade to a broader one, not to
    # an apology.
    if mood:
        item = await delivery.deliver_one(
            bot, message, feature=Feature.VOICE, kinds=(ContentKind.VOICE,)
        )
        if item is not None:
            return

    await message.answer("no recordings here yet 🎙 (tell aqeef to record some)")
