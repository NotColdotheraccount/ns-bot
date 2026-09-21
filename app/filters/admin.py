"""Filter restricting a handler to the admin.

The authorization middleware already guarantees that only you or your
girlfriend reach any handler. This filter draws the second line: which of the
two of you is allowed.

It reads the `is_admin` flag the middleware put into the handler data, so the
comparison logic lives in exactly one place.
"""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import TelegramObject


class IsAdmin(Filter):
    """Passes only for the admin user."""

    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return is_admin
