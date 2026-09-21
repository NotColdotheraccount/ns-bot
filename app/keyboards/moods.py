"""Inline keyboards for mood selection.

## Why a CallbackData factory instead of raw strings

Telegram gives each button a `callback_data` string with a hard **64-byte
limit**, and it arrives back as an opaque blob. Hand-rolling that means parsing
strings like "mood:sad:bad_day" by hand and getting it wrong when a value
contains a colon.

aiogram's CallbackData factory handles packing, unpacking and filtering, and it
type-checks the fields. It also fails loudly at build time if the packed string
would exceed 64 bytes — far better than a button that silently does nothing in
production.

## Why buttons here and not everywhere

Your spec said not to put buttons everywhere, which is right. The rule used in
this project: buttons when the bot needs to *ask her something* with a small
fixed set of answers. Everything else stays natural language. She should not
have to learn an interface to talk to you.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class MoodCB(CallbackData, prefix="mood"):
    """Payload for a Bad Day mood button.

    Packs to e.g. "mood:overthinking" — well inside the 64-byte limit, with
    room to add fields later without breaking existing buttons.
    """

    mood: str


# (emoji label, internal tag). The tag must match tags used in your content
# YAML, which is what ties a button press to the right reassurance.
BAD_DAY_MOODS: tuple[tuple[str, str], ...] = (
    ("😔 Sad", "sad"),
    ("😰 Stressed", "stress"),
    ("🧠 Overthinking", "overthinking"),
    ("🥺 Missing you", "missing_me"),
    ("😡 Frustrated", "frustrated"),
    ("❤️ Just comfort me", "comfort"),
)


def bad_day_keyboard() -> InlineKeyboardMarkup:
    """Two-column grid of mood buttons.

    Two columns rather than one long list: on a phone, six stacked full-width
    buttons push the conversation off screen.
    """
    buttons = [
        InlineKeyboardButton(text=label, callback_data=MoodCB(mood=tag).pack())
        for label, tag in BAD_DAY_MOODS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mood_label(tag: str) -> str:
    """Human label for a tag, for confirmation text."""
    for label, value in BAD_DAY_MOODS:
        if value == tag:
            return label
    return tag
