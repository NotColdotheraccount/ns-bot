"""Fallback for messages in topics that are not bound to any feature.

This router MUST be registered last. aiogram tries routers in registration
order, so anything registered after it would be unreachable.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.filters.admin import IsAdmin
from app.filters.topic import InUnboundTopic

logger = logging.getLogger(__name__)

router = Router(name="fallback")


@router.message(InUnboundTopic(), IsAdmin(), F.text)
async def unbound_topic_admin(message: Message) -> None:
    """Tell the admin that this topic has no feature yet.

    Only fires for you. For your girlfriend the bot stays silent, so a topic
    you have not configured looks like a quiet room rather than a broken bot.
    """
    logger.info("Admin message in unbound topic | thread=%s", message.message_thread_id)
    await message.answer(
        "ℹ️ This topic is not bound to a feature yet.\n"
        f"Thread ID: <code>{message.message_thread_id}</code>\n\n"
        "Run <code>/bind &lt;feature&gt;</code> here, or <code>/bindings</code> "
        "to see what is left."
    )
