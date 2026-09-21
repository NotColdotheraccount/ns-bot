"""#OurMemories — photos and the stories attached to them.

Natural language first, command second. She should be able to type "another"
and get a memory; /memory 17 exists for when she wants a specific one, but she
never has to learn it.
"""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.features import Feature
from app.filters.topic import BoundTo
from app.intents import extract_mood, normalise
from app.services.delivery import ContentDelivery
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

router = Router(name="memories")

# Matches "memory 17", "memory #17", "number 17", "#17", "17"
_NUMBER_RE = re.compile(r"(?:memory|number|no|#)?\s*#?(\d{1,4})\b")

_TAG_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("funny", "laugh", "stupid", "silly"), "funny"),
    (("early", "first", "beginning", "start"), "early"),
    (("date", "dates"), "date"),
    (("food", "eat", "ate", "dinner", "lunch"), "food"),
    (("trip", "travel", "holiday", "vacation"), "trip"),
)


def _requested_number(text: str) -> int | None:
    """Extract a memory number, but only when it is clearly a request.

    A bare number is accepted because 'memory 17' and '17' both read naturally
    in this topic. A number inside a longer sentence is ignored, so "we went
    there like 3 times" does not fetch memory 3.
    """
    normalised = normalise(text)
    if len(normalised.split()) > 3:
        return None
    match = _NUMBER_RE.fullmatch(normalised.strip())
    if match is None:
        return None
    return int(match.group(1))


def _tags_for(text: str) -> tuple[str, ...]:
    normalised = normalise(text)
    for keywords, tag in _TAG_KEYWORDS:
        if any(keyword in normalised for keyword in keywords):
            return (tag,)
    mood = extract_mood(text)
    return (mood,) if mood else ()


@router.message(BoundTo(Feature.MEMORIES), Command("memory"))
async def cmd_memory(
    message: Message,
    command: CommandObject,
    bot: Bot,
    memory_service: MemoryService,
    delivery: ContentDelivery,
) -> None:
    """/memory 17 — fetch a specific memory by number."""
    if not command.args or not command.args.strip().isdigit():
        await message.answer("try <code>/memory 3</code> — or just say “another” 🙂")
        return
    await _send_numbered(bot, message, memory_service, delivery, int(command.args.strip()))


@router.message(BoundTo(Feature.MEMORIES), F.text)
async def handle_memories(
    message: Message,
    bot: Bot,
    memory_service: MemoryService,
    delivery: ContentDelivery,
) -> None:
    """Natural-language memory requests."""
    text = message.text or ""

    number = _requested_number(text)
    if number is not None:
        await _send_numbered(bot, message, memory_service, delivery, number)
        return

    tags = _tags_for(text)
    logger.info("memories | tags=%s", list(tags))

    await delivery.typing(bot, message, action="upload_photo")

    memory = await memory_service.choose(tags=tags)
    if memory is None and tags:
        # Narrow request with no match degrades to any memory rather than an
        # apology.
        memory = await memory_service.choose()

    if memory is None:
        await message.answer("no memories saved yet 📸")
        return

    await _deliver(bot, message, memory_service, memory)


async def _send_numbered(
    bot: Bot,
    message: Message,
    memory_service: MemoryService,
    delivery: ContentDelivery,
    number: int,
) -> None:
    memory = memory_service.by_number(number)
    if memory is None:
        total = memory_service.count
        await message.answer(
            f"there's no memory #{number} 🥺" + (f" (i've saved {total} so far)" if total else "")
        )
        return

    await delivery.typing(bot, message, action="upload_photo")
    await _deliver(bot, message, memory_service, memory)


async def _deliver(
    bot: Bot, message: Message, memory_service: MemoryService, memory
) -> None:
    sent = await memory_service.send(
        bot,
        memory,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
    )
    if not sent:
        await message.answer("something went wrong sending that one 🥺")
        return

    user_id = message.from_user.id if message.from_user else 0
    await memory_service.record_sent(
        memory, user_id=user_id, feature=Feature.MEMORIES.value
    )
    logger.info("Delivered memory | id=%s number=%s", memory.id, memory.number)
