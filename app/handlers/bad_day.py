"""#BadDay — a short, gentle two-step flow.

She says she had a bad day; the bot asks what kind, then sends content matching
that mood. Two steps, then it stops. Your spec said not to make this behave like
a therapist, and the main way bots get that wrong is by continuing to probe.
This one asks once and then just gives her something.

## Why buttons here

"Bad day" covers stressed, sad, overthinking and frustrated, and those want
genuinely different responses. Guessing from free text would be wrong often
enough to feel careless. Six buttons is one tap, needs no typing on a phone,
and is honest about the fact that the bot is choosing from fixed categories.

## Why this state is not stored

The mood is packed into the button's callback_data and comes back with the tap,
so nothing needs to be remembered between the two steps. No FSM, no database
row, nothing to expire or leak between topics. If she ignores the buttons
entirely, there is no dangling state to clean up.
"""

from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.content.schema import ContentKind
from app.features import Feature
from app.filters.topic import BoundTo
from app.intents import Intent, detect_intent
from app.keyboards.moods import MoodCB, bad_day_keyboard
from app.services.delivery import ContentDelivery

logger = logging.getLogger(__name__)

router = Router(name="bad_day")

# Chance of following the written comfort with a real voice note.
VOICE_FOLLOWUP_CHANCE = 0.6

_PROMPTS = (
    "what kind of bad day is it? 🥺",
    "oh no. what kind of bad is it?",
    "tell me which one it is and i'll pick something 🥺",
)


@router.message(BoundTo(Feature.BAD_DAY), F.text)
async def handle_bad_day(message: Message, bot: Bot, delivery: ContentDelivery) -> None:
    """Ask which kind of bad day, unless she already said."""
    text = message.text or ""
    intent = detect_intent(text)
    logger.info("bad_day | intent=%s", intent.value)

    await delivery.typing(bot, message)

    # If she already named the mood ("something for overthinking"), skip the
    # question entirely. Asking a question she has already answered is the
    # fastest way to make a bot feel like it is not listening.
    direct = _direct_mood(text)
    if direct is not None:
        await _send_comfort(bot, message, delivery, mood=direct)
        return

    await message.answer(random.choice(_PROMPTS), reply_markup=bad_day_keyboard())


@router.callback_query(MoodCB.filter())
async def handle_mood_choice(
    callback: CallbackQuery,
    callback_data: MoodCB,
    bot: Bot,
    delivery: ContentDelivery,
) -> None:
    """Handle a mood button tap."""
    # Telegram shows a loading spinner on the button until this is answered.
    # Skip it and the button appears stuck for several seconds.
    await callback.answer()

    message = callback.message
    if message is None:
        return

    # Remove the keyboard so the buttons cannot be tapped again on an old
    # message days later. The text stays, so the conversation still reads.
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        # Already edited or too old to edit. Harmless.
        pass

    logger.info("bad_day | mood=%s", callback_data.mood)
    await _send_comfort(
        bot, message, delivery, mood=callback_data.mood, user_id=callback.from_user.id
    )


# ---------------------------------------------------------------- internals


def _direct_mood(text: str) -> str | None:
    """Detect a mood she named explicitly in her message."""
    from app.intents import normalise

    normalised = normalise(text)
    for keyword, tag in (
        ("overthink", "overthinking"),
        ("stress", "stress"),
        ("frustrat", "frustrated"),
        ("angry", "frustrated"),
        ("annoyed", "frustrated"),
        ("lonely", "missing_me"),
    ):
        if keyword in normalised:
            return tag
    return None


async def _send_comfort(
    bot: Bot,
    message: Message,
    delivery: ContentDelivery,
    *,
    mood: str,
    user_id: int | None = None,
) -> None:
    """Send written comfort, then often a voice note."""
    await delivery.typing(bot, message)

    # Fall back to the broader 'comfort' tag if nothing matches the specific
    # mood, so a category you have not written for yet still gets a reply.
    item = await delivery.deliver_one(
        bot, message, feature=Feature.BAD_DAY, kinds=(ContentKind.TEXT,), tags=(mood,)
    )
    if item is None:
        item = await delivery.deliver_one(
            bot,
            message,
            feature=Feature.BAD_DAY,
            kinds=(ContentKind.TEXT,),
            tags=("comfort", "general"),
        )

    if item is None:
        await message.answer("i haven't written anything for this one yet 🥺")
        return

    if random.random() > VOICE_FOLLOWUP_CHANCE:
        return

    await asyncio.sleep(1.4)
    await delivery.typing(bot, message, action="record_voice")
    await delivery.deliver_one(
        bot,
        message,
        feature=Feature.BAD_DAY,
        kinds=(ContentKind.VOICE,),
        tags=(mood, "comfort"),
    )
