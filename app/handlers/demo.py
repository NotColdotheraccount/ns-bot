"""TEMPORARY: proves topic routing works before real features exist.

Echoes which feature owns the topic a message was sent in. Delete this router
once real feature handlers replace it — it is scaffolding, not product.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.features import Feature
from app.filters.topic import InBoundTopic

logger = logging.getLogger(__name__)

router = Router(name="demo")


@router.message(InBoundTopic(), F.text)
async def echo_feature(message: Message, feature: Feature) -> None:
    """`feature` is injected by InBoundTopic returning a dict."""
    logger.info(
        "Routed message | feature=%s thread=%s", feature.value, message.message_thread_id
    )
    await message.answer(
        f"🧭 Routed to <b>{feature.label}</b>\n"
        f"<i>(placeholder — the real handler arrives in a later stage)</i>"
    )
