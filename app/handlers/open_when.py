"""#OpenWhen — she picks which letter she needs.

Unlike every other feature, the bot does not choose here. That is the point of
an Open When: the envelope she reaches for says something about how she feels
right now, and taking that choice away would remove most of the meaning.

Keyboards are rebuilt on every request rather than edited in place, so the list
always reflects what is unlocked today.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.content.open_when_library import OpenWhenLibrary
from app.content.open_when_schema import OpenWhen
from app.features import Feature
from app.filters.topic import BoundTo
from app.keyboards.open_when import (
    OpenWhenCB,
    OpenWhenLockedCB,
    open_when_keyboard,
)
from app.services.delivery import ContentDelivery
from app.services.letter_service import LetterService

logger = logging.getLogger(__name__)

router = Router(name="open_when")


@router.message(BoundTo(Feature.OPEN_WHEN), F.text)
async def handle_open_when(
    message: Message,
    open_when_library: OpenWhenLibrary,
    letter_service: LetterService,
) -> None:
    """Show the list of letters."""
    enlistment = await letter_service.enlistment_date()
    today = letter_service.today()

    unlocked = open_when_library.unlocked(today, enlistment)
    locked = open_when_library.locked(today, enlistment)

    if not unlocked and not locked:
        await message.answer("no open-when letters written yet 💌")
        return

    header = "open when…" if unlocked else "nothing unlocked yet 🔒"
    await message.answer(header, reply_markup=open_when_keyboard(unlocked, locked))


@router.callback_query(OpenWhenLockedCB.filter())
async def handle_locked(
    callback: CallbackQuery,
    callback_data: OpenWhenLockedCB,
    open_when_library: OpenWhenLibrary,
    letter_service: LetterService,
) -> None:
    """Tapped a locked letter — show when it opens, in a popup."""
    letter = open_when_library.get(callback_data.letter_id)
    if letter is None:
        await callback.answer("that letter isn't there anymore 🥺", show_alert=True)
        return

    enlistment = await letter_service.enlistment_date()
    unlock = letter.unlocks_on(enlistment)
    when = unlock.strftime("%d %b %Y") if unlock else "soon"

    logger.info("open_when locked tap | id=%s", letter.id)

    # The single answer for this tap. Telegram accepts ONE answer per tap, so
    # an earlier plain answer() would silently swallow this popup.
    await callback.answer(f"not yet 🔒\nthis one opens on {when}", show_alert=True)


@router.callback_query(OpenWhenCB.filter())
async def handle_open(
    callback: CallbackQuery,
    callback_data: OpenWhenCB,
    bot: Bot,
    open_when_library: OpenWhenLibrary,
    letter_service: LetterService,
    delivery: ContentDelivery,
) -> None:
    """Open a letter."""
    message = callback.message
    letter = open_when_library.get(callback_data.letter_id)

    if message is None or letter is None:
        await callback.answer("that letter isn't there anymore 🥺", show_alert=True)
        return

    # Re-check the unlock at open time. The keyboard could be hours old.
    enlistment = await letter_service.enlistment_date()
    if not letter.is_unlocked(letter_service.today(), enlistment):
        await callback.answer("not yet 🔒", show_alert=True)
        return

    # One answer per tap: answered here, before the slower sends.
    await callback.answer()

    logger.info("open_when opened | id=%s", letter.id)

    await delivery.typing(bot, message)
    await _send(bot, message, open_when_library, letter)


async def _send(
    bot: Bot, message: Message, library: OpenWhenLibrary, letter: OpenWhen
) -> None:
    chat_id = message.chat.id
    thread_id = message.message_thread_id

    text = f"💌 <b>Open when {letter.title}</b>\n\n{letter.body}"
    if len(text) > 4096:
        text = text[:4090].rstrip() + "…"

    await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=text)

    photo = library.resolve(letter.photo)
    if photo is not None:
        await bot.send_photo(
            chat_id=chat_id, message_thread_id=thread_id, photo=FSInputFile(photo)
        )

    video = library.resolve(letter.video)
    if video is not None:
        await bot.send_video(
            chat_id=chat_id, message_thread_id=thread_id, video=FSInputFile(video)
        )

    voice = library.resolve(letter.voice)
    if voice is not None:
        await asyncio.sleep(1.0)
        await bot.send_voice(
            chat_id=chat_id, message_thread_id=thread_id, voice=FSInputFile(voice)
        )

    if letter.followup:
        await asyncio.sleep(2.0)
        await bot.send_message(
            chat_id=chat_id, message_thread_id=thread_id, text=letter.followup
        )
