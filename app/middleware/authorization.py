"""Authorization middleware — the single security gate for the whole bot.

Registered as an *outer* middleware on the update observer, meaning it runs
before aiogram evaluates any filter or handler. Nothing downstream executes
unless this class explicitly allows it.

Doing the check here rather than at the top of each handler means there is one
place to get right and one place to audit. With ~15 features planned, an
`if user_id != ADMIN` line repeated in every handler is a matter of time before
one gets forgotten.

Rules enforced, in order:
  1. The update must come from a known user.
  2. That user must be the admin or the girlfriend.
  3. Group traffic must come from the one configured supergroup.
  4. Private chats are allowed only for those two users.

Anything rejected is dropped silently — no reply. Replying to strangers would
confirm the bot exists and is live, which is the opposite of what a private
bot wants.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, User

from app.config import Settings

logger = logging.getLogger(__name__)

# Chat types that represent a group conversation.
_GROUP_CHAT_TYPES = frozenset({"group", "supergroup"})


class AuthorizationMiddleware(BaseMiddleware):
    """Reject every update that does not come from an authorized source."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # aiogram's built-in UserContextMiddleware populates these before our
        # middleware runs, so we get the user and chat without having to unpack
        # every possible update type (message, callback_query, edited_message...).
        user: User | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")

        if user is None:
            # Channel posts and some service updates carry no user. Nothing in
            # this bot needs them.
            logger.debug("Dropped update with no associated user.")
            return None

        if user.id not in self._settings.authorized_user_ids:
            # Logged at WARNING with the ID on purpose: if you ever mistype your
            # own ID in .env and lock yourself out, this line in the terminal
            # tells you exactly what value to put back.
            logger.warning(
                "Rejected unauthorized user | user_id=%s chat_type=%s",
                user.id,
                chat.type if chat else "unknown",
            )
            return None

        if chat is not None and chat.type in _GROUP_CHAT_TYPES:
            if chat.id != self._settings.telegram_group_id:
                logger.warning(
                    "Rejected update from unexpected group | chat_id=%s user_id=%s",
                    chat.id,
                    user.id,
                )
                return None

        # Passed every check. Expose derived facts so handlers can depend on
        # them as plain arguments instead of importing global configuration.
        data["settings"] = self._settings
        data["is_admin"] = self._settings.is_admin(user.id)
        data["is_group"] = chat is not None and chat.type in _GROUP_CHAT_TYPES

        return await handler(event, data)
