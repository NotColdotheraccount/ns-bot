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

_MISS_TAGS = ("missing_me",)

# Answers to "why do you miss me" — a question, not a statement, so it needs
# its own pool. Keep the trailing comma: without it this is a string, and the
# tag filter would loop over its characters and match nothing.
_WHY_MISS_TAGS = ("why_miss_me",)


@router.message(BoundTo(Feature.MISS_ME), F.text)
async def handle_miss_me(
    message: Message, bot: Bot, delivery: ContentDelivery
) -> None:
    intent = detect_intent(message.text or "")
    logger.info("miss_me | intent=%s", intent.value)

    await delivery.typing(bot, message)

    # "why do you miss me" answers the question; "another" is a plain reroll
    # with no filter; anything else is an ordinary missing-you reply.
    if intent is Intent.WHY_MISS:
        tags = _WHY_MISS_TAGS
    elif intent is Intent.ANOTHER:
        tags = ()
    else:
        tags = _MISS_TAGS

    text_item = await delivery.deliver_one(
        bot, message, feature=Feature.MISS_ME, kinds=(ContentKind.TEXT,), tags=tags
    )

    # A why-question with no why content falls back to an ordinary reply
    # rather than an apology — answering slightly off is better than the bot
    # telling her nothing was written.
    if text_item is None and intent is Intent.WHY_MISS:
        text_item = await delivery.deliver_one(
            bot,
            message,
            feature=Feature.MISS_ME,
            kinds=(ContentKind.TEXT,),
            tags=_MISS_TAGS,
        )

    if text_item is None:
        await message.answer(
            "most likely got problems (tell aqeef)"
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