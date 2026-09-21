"""Picks content, sends it, and records the send — in that order.

Every feature does the same three steps, so they live here once rather than
being copy-pasted into fifteen handlers. Getting the order wrong is the subtle
part: the send must be recorded *only after* Telegram accepted it, or a failed
upload would permanently suppress a piece of content she never received.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import Message

from app.content.schema import ContentItem, ContentKind
from app.features import Feature
from app.services.content_selector import ContentSelector
from app.services.media_service import MediaService

logger = logging.getLogger(__name__)


class ContentDelivery:
    """Feature-facing helper: 'send her something that fits this situation'."""

    def __init__(self, selector: ContentSelector, media: MediaService) -> None:
        self._selector = selector
        self._media = media

    async def deliver_one(
        self,
        bot: Bot,
        message: Message,
        *,
        feature: Feature,
        kinds: tuple[ContentKind, ...] = (),
        tags: tuple[str, ...] = (),
        exclude_ids: tuple[str, ...] = (),
        caption: str | None = None,
    ) -> ContentItem | None:
        """Choose one item, send it, record it. Returns the item, or None."""
        item = await self._selector.choose(
            kinds=kinds, tags=tags, exclude_ids=exclude_ids
        )
        if item is None:
            return None

        sent = await self._media.send(
            bot,
            item,
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            caption=caption,
        )
        if not sent:
            # Deliberately not recorded: she did not receive it, so it must
            # stay eligible for selection next time.
            logger.warning("Delivery failed | feature=%s id=%s", feature.value, item.id)
            return None

        user_id = message.from_user.id if message.from_user else 0
        await self._selector.record_sent(item, user_id=user_id, feature=feature.value)
        logger.info(
            "Delivered | feature=%s kind=%s id=%s", feature.value, item.kind.value, item.id
        )
        return item

    async def typing(self, bot: Bot, message: Message, action: str = "typing") -> None:
        """Show a chat action so a reply does not appear instantly.

        Small thing, but an instant reply reads as a machine. A brief 'typing…'
        makes the exchange feel less abrupt. Failures here are ignored — a
        missing typing indicator must never block the actual message.
        """
        try:
            await bot.send_chat_action(
                chat_id=message.chat.id,
                action=action,
                message_thread_id=message.message_thread_id,
            )
        except Exception:  # noqa: BLE001 — cosmetic only
            pass
