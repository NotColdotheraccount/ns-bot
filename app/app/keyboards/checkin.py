"""Daily check-in mood buttons."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class CheckInCB(CallbackData, prefix="ci"):
    """Payload for a check-in button.

    `day` is included so a tap on yesterday's prompt cannot be recorded as
    today's answer. Without it, scrolling up and tapping an old message would
    silently overwrite the wrong day.
    """

    mood: str
    day: str  # YYYY-MM-DD, Singapore local


# (label, internal mood, is_low) — is_low marks answers that get real comfort.
CHECKIN_MOODS: tuple[tuple[str, str, bool], ...] = (
    ("🥰", "amazing", False),
    ("😊", "good", False),
    ("😐", "okay", False),
    ("😔", "bad", True),
    ("😭", "terrible", True),
)


def checkin_keyboard(day: str = "") -> InlineKeyboardMarkup:
    """Single row of five emoji — one tap, no reading required."""
    buttons = [
        InlineKeyboardButton(
            text=label, callback_data=CheckInCB(mood=mood, day=day).pack()
        )
        for label, mood, _low in CHECKIN_MOODS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def is_low_mood(mood: str) -> bool:
    return any(value == mood and low for _label, value, low in CHECKIN_MOODS)
