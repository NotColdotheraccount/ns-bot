"""Responses to the daily check-in.

The prompt is posted by the scheduler; this handles the tap.

Responses differ by mood, and low moods get real comfort rather than a canned
"hope tomorrow is better". But it answers once and stops — your spec was clear
about not spamming follow-ups, and a bot that keeps going after a bad day
answer stops feeling like you and starts feeling like a survey.
"""

from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.content.schema import ContentKind
from app.database.repositories.settings import CheckInRepository
from app.database.session import Database
from app.features import Feature
from app.keyboards.checkin import CheckInCB, is_low_mood
from app.services.delivery import ContentDelivery

logger = logging.getLogger(__name__)

router = Router(name="checkin")

_REPLIES: dict[str, tuple[str, ...]] = {
    "amazing": (
        "good!! i want to hear about it 🥰",
        "that's what i like to see. tell me everything later",
    ),
    "good": (
        "glad today was alright ❤️",
        "good. that's enough.",
    ),
    "okay": (
        "okay days are fine. not everything has to be a big one.",
        "fair. an okay day is still a day done.",
    ),
    "bad": (
        "sorry today was rough 🥺 here, i left you something",
        "that's alright. you don't have to fix it tonight.",
    ),
    "terrible": (
        "hey. i'm sorry 🥺 i left this for exactly today",
        "okay that's a hard one. come here.",
    ),
}


@router.callback_query(CheckInCB.filter())
async def handle_checkin(
    callback: CallbackQuery,
    callback_data: CheckInCB,
    bot: Bot,
    database: Database,
    delivery: ContentDelivery,
) -> None:
    await callback.answer()

    message = callback.message
    if message is None:
        return

    # Remove the buttons so an old prompt cannot be answered later.
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    mood = callback_data.mood
    day = callback_data.day

    async with database.session() as session:
        recorded = await CheckInRepository(session).record(
            local_date=day, mood=mood, user_id=callback.from_user.id
        )

    if not recorded:
        # Already answered for that day — most likely an old prompt was tapped.
        await message.answer("already got your answer for that day 🙂")
        return

    logger.info("checkin recorded | mood=%s", mood)

    await delivery.typing(bot, message)
    await message.answer(random.choice(_REPLIES.get(mood, ("noted ❤️",))))

    if not is_low_mood(mood):
        return

    # Low mood: follow with something real, once.
    await asyncio.sleep(1.2)
    tags = ("comfort", "bad_day") if mood == "bad" else ("comfort", "sad", "bad_day")

    item = await delivery.deliver_one(
        bot, message, feature=Feature.DAILY_CHECKIN, kinds=(ContentKind.TEXT,), tags=tags
    )

    if item is not None and random.random() < 0.6:
        await asyncio.sleep(1.2)
        await delivery.typing(bot, message, action="record_voice")
        await delivery.deliver_one(
            bot,
            message,
            feature=Feature.DAILY_CHECKIN,
            kinds=(ContentKind.VOICE,),
            tags=tags,
        )
