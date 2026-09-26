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
        "YAYYYYYY BABYYYY im glad today was amazingggg",
        "THATS GOODDDD BABYYYY tell me everythingggg",
        "yayyyyy im happy you had a good day babyyy",
        "OOOOOO amazingggg?? tell me what happenedddd",
        "GOODDDDD thats what i like to hearrrr",
        "YAY BABYYYYY im so glad today went welllll",
        "hehehehe gooddddd tell me abt your dayyy",
        "AMAZINGGGG??? okayyyy i need to hear everything",
        "YAYYYYYYY GOOD DAY FOR BABYYYY",
        "awwwww im glad you had an amazing dayyy",
        "GOODDDD BABYYYYY what made today so goodddd",
        "hehe thats goodddd im happy for you babyyy",
        "YAYYYYY tell me the best part of todayyyy",
        "OOOOOOO GOOD DAYYYY I LIKE THAT",
        "goodgoodgooddddd im glad today was niceee",
        "YAYYYY BABYYYY what happenedd tell meee",
        "THATS WHAT I WANNA HEARRRRR",
        "amazinggggg babyyyy im glad today treated you wellll",
        "hehehehe YAYYYYY today was a good dayyyy",
        "GOODDDD now tell me everything that happenedd todayyy",
    ),

    "good": (
        "yayyyy goodddd im glad today was good babyyy",
        "goodddd babyyyy thats nice to hearrr",
        "YAYYYY im glad today went welllll",
        "hehe goodgoodddd tell me abt todayyy",
        "awwww okay goodddd babyyyy",
        "GOODDDD thats what i wanna hearrrr",
        "yayyyyy at least today was gooddd",
        "hehehehe im glad babyyyy",
        "goodddd baby what did you do todayyy",
        "YAYYYY GOOD DAYYYY",
        "awww im happy today was good for youuu",
        "goodgoodgoodddd babyyyy",
        "hehe okayyyy thats goodddd",
        "GOODDDD was anything fun todayyy?",
        "yayyy babyyyy im glad you had a good day",
        "thats goodddd hehe tell me what happened todayyy",
        "OOOOO okay goodddd babyyyy",
        "goodddd im glad today treated you wellll",
        "YAYYYYY babyyyyyy",
        "hehehehe thats niceeee im glad today was good",
    ),

    "okay": (
        "okayyyy babyyyy at least today wasnt too baddd",
        "just okayyy? what happenedd today babyyy",
        "okayyyy babyyy how are you feeling nowww",
        "hmmmm okayyyy tell me abt todayyy",
        "okayokayyy babyyyy hopefully tomorrow is betterrr",
        "just an okay dayyy huhhh",
        "okayyy babyyy you made it through todayyy",
        "hmmmm what made today just okayyy?",
        "okayyyy thats okay babyyyy",
        "fairrrr babyyy some days are just like thattt",
        "okayyy babyyyy get some rest tonight okayyy",
        "hmmmm okayyyy i wanna hear abt ittt",
        "okayyy baby was today tiringgg?",
        "thats okayyyy babyyyy tomorrow new dayyy",
        "okayokayyy at least today is doneee",
        "just okayyyy? come tell me what happenedd",
        "okayyyy babyyyy hope youre feeling alrighttt",
        "hmmmm okayyy did anything happen todayyy?",
        "okayyyy you got through today babyyy",
        "thats okayyy not every day needs to be amazinggg",
    ),

    "bad": (
        "awww babyyyy im sorry today was baddd",
        "oh noooo babyyyy what happenedd today",
        "babyyyy :( im sorry today wasnt good",
        "awwww come hereeee babyyyy",
        "hmmmm babyyyy tell me what happenedd",
        "im sorryyy babyyy today sounds roughhh",
        "awww noooo i hope youre okay babyyyy",
        "babyyyyy :( you wanna tell me abt todayyy?",
        "its okayyy babyyyy today is over alrrr",
        "awwww im sorry baby hopefully tomorrow is betterrr",
        "nooooo babyyyy not a bad dayyy :(",
        "hmmmm come tell me what happeneddd babyyy",
        "babyyyy im sorry today treated you badlyyy",
        "awwwww rest well tonight okayyyy",
        "its okay baby you made it through todayyy",
        "oh noooo :( i hope youre feeling better nowww",
        "babyyyy dont keep everything to yourself okayyy",
        "awww im sorryyy today was rough babyyy",
        "hmmmm bad dayyy :( come tell me abt it",
        "its okayyyy babyyy tomorrow can be betterrr",
    ),

    "terrible": (
        "oh noooo babyyyy :( im so sorry today was terrible",
        "BABYYYYY :( what happenedd today",
        "awwww babyyyy come hereeee",
        "noooooo baby im sorry today was that baddd",
        "babyyyy :( please rest properly tonight okayyy",
        "awwwwww tell me what happened babyyyy",
        "hmmmm babyyyy today sounds really roughhh",
        "im sorryyy babyyy you didnt deserve such a bad day",
        "babyyyy :( at least today is over nowww",
        "awww noooo i hope youre okay babyyyy",
        "terribleeee?? :( babyyyy what happenedd",
        "come hereeee babyyyy its okayyy",
        "awww baby im really sorry today went like thattt",
        "babyyyyy :( take it easy tonight okayyy",
        "hmmmm im hereeee tell me abt todayyy",
        "noooo not my babyyy having a terrible dayyy :(",
        "awwwwww i wish today treated you betterrr",
        "its okay babyyyy you got through todayyy",
        "babyyyy :( tomorrow is a new day okayyy",
        "awwww come restttt youve had enough for todayyy",
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
