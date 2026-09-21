"""#Reassurance — natural language, no buttons.

Unlike Bad Day, this topic does not ask anything. She types how she feels and
gets something you wrote. Adding a button step here would put a form in front
of a person who just wants to hear from you.

Routing is keyword-based: her words are mapped to content tags directly. If
nothing matches, it falls back to general comfort rather than asking her to
clarify.
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
from app.intents import normalise
from app.services.delivery import ContentDelivery

logger = logging.getLogger(__name__)

router = Router(name="reassurance")

VOICE_FOLLOWUP_CHANCE = 0.4

# Keyword -> content tag. First match wins, so more specific phrases go first.
_TAG_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("overthink", "spiralling", "spiraling", "in my head", "cant stop thinking"), "overthinking"),
    (("not good enough", "insecure", "ugly", "hate myself", "deserve"), "insecurity"),
    (("cant sleep", "cannot sleep", "insomnia", "3am", "2am", "awake"), "sleep"),
    (("exam", "work", "school", "deadline", "assignment", "stress", "busy"), "stress"),
    (("lonely", "alone", "by myself"), "missing_me"),
    (("we argued", "we fought", "argument", "fight"), "argument"),
    (("tired", "exhausted", "drained", "burnt out", "burned out"), "bad_day"),
    (("miss you", "miss u", "miss him"), "missing_me"),
)


def _tags_for(text: str) -> tuple[str, ...]:
    """Map her words to content tags, or fall back to general comfort."""
    normalised = normalise(text)
    for keywords, tag in _TAG_KEYWORDS:
        if any(keyword in normalised for keyword in keywords):
            return (tag, "comfort")
    return ("comfort", "general", "reassurance")


@router.message(BoundTo(Feature.REASSURANCE), F.text)
async def handle_reassurance(
    message: Message, bot: Bot, delivery: ContentDelivery
) -> None:
    tags = _tags_for(message.text or "")
    logger.info("reassurance | tags=%s", list(tags))

    await delivery.typing(bot, message)

    item = await delivery.deliver_one(
        bot, message, feature=Feature.REASSURANCE, kinds=(ContentKind.TEXT,), tags=tags
    )
    if item is None:
        item = await delivery.deliver_one(
            bot, message, feature=Feature.REASSURANCE, kinds=(ContentKind.TEXT,)
        )
    if item is None:
        await message.answer("nothing written here yet 🥺")
        return

    if random.random() > VOICE_FOLLOWUP_CHANCE:
        return

    await asyncio.sleep(1.2)
    await delivery.typing(bot, message, action="record_voice")
    await delivery.deliver_one(
        bot, message, feature=Feature.REASSURANCE, kinds=(ContentKind.VOICE,), tags=tags
    )
