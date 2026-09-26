"""#MissMe — the topic she opens when she misses you.

Sends something you wrote, and often follows it with your actual voice. The
voice note is the point; the text is the lead-in.
"""

from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.content.schema import ContentKind
from app.features import Feature
from app.filters.topic import BoundTo
from app.intents import Intent, detect_intent
from app.services.delivery import ContentDelivery

logger = logging.getLogger(__name__)

router = Router(name="miss_me")

# Chance of following the written message with a real voice note. Not 100%:
# something that happens every single time stops feeling like a moment.
VOICE_FOLLOWUP_CHANCE = 0.55

_MISS_TAGS = ("missing_me")


@router.message(BoundTo(Feature.MISS_ME), F.text)
async def handle_miss_me(
    message: Message, bot: Bot, delivery: ContentDelivery
) -> None:
    intent = detect_intent(message.text or "")
    logger.info("miss_me | intent=%s", intent.value)

    await delivery.typing(bot, message)

    # "i miss you" gets comfort-weighted tags; "another" is a plain reroll.
    tags = _MISS_TAGS if intent is not Intent.ANOTHER else ()

    text_item = await delivery.deliver_one(
        bot, message, feature=Feature.MISS_ME, kinds=(ContentKind.TEXT,), tags=tags
    )

    if text_item is None:
        await message.answer(
            "i haven't written anything for this yet 🥺 (tell aqeef)"
        )
        return

    if random.random() > VOICE_FOLLOWUP_CHANCE:
        return

    # Brief pause so the voice note does not land in the same instant as the
    # text — it reads as two separate thoughts rather than one dump.
    await asyncio.sleep(1.2)
    await delivery.typing(bot, message, action="record_voice")

    await delivery.deliver_one(
        bot,
        message,
        feature=Feature.MISS_ME,
        kinds=(ContentKind.VOICE,),
        tags=_MISS_TAGS,
    )
