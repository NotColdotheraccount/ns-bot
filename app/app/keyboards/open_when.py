"""Keyboard listing the Open When letters.

## The callback_data length problem

Every button carries at most 64 bytes. The prefix "ow:" plus a letter id must
fit, which is why OpenWhen.id is capped at 48 characters in the schema — the
limit is enforced where the data is authored, not discovered when a button
silently stops working in production.

## Why locked letters are still shown

A locked letter appears with 🔒 rather than being hidden. Hiding it would make
the list change shape over time for no visible reason. Showing it tells her
something exists and is coming, which is the same thing a sealed envelope with
writing on it does.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.content.open_when_schema import OpenWhen

# Telegram allows 100 buttons, but a list longer than this stops being
# browsable on a phone.
MAX_BUTTONS = 14


class OpenWhenCB(CallbackData, prefix="ow"):
    """Which letter she tapped."""

    letter_id: str


class OpenWhenLockedCB(CallbackData, prefix="owl"):
    """A locked letter — answered with a hint, not a letter."""

    letter_id: str


def open_when_keyboard(
    unlocked: list[OpenWhen], locked: list[OpenWhen]
) -> InlineKeyboardMarkup:
    """One letter per row — titles are sentences, not labels."""
    rows: list[list[InlineKeyboardButton]] = []

    for letter in unlocked[:MAX_BUTTONS]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💌 {letter.title}",
                    callback_data=OpenWhenCB(letter_id=letter.id).pack(),
                )
            ]
        )

    remaining = MAX_BUTTONS - len(rows)
    for letter in locked[:remaining]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🔒 {letter.title}",
                    callback_data=OpenWhenLockedCB(letter_id=letter.id).pack(),
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)
