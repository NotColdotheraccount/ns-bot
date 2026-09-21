"""Filters that route a message to the feature owning its topic.

This is the mechanism replacing a hand-written TopicRouter. aiogram already
dispatches on filters, so a feature router simply declares which feature it
serves and the framework handles the rest:

    router.message(BoundTo(Feature.MEMORIES))

Filters receive the same injected data as handlers, which is how topic_service
arrives here without any global lookup.
"""

from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import Message

from app.features import Feature
from app.services.topic_service import TopicService


class BoundTo(Filter):
    """Passes when the message's topic is bound to the given feature."""

    def __init__(self, feature: Feature) -> None:
        self.feature = feature

    async def __call__(self, message: Message, topic_service: TopicService) -> bool:
        resolved = topic_service.resolve(message.chat.id, message.message_thread_id)
        return resolved is self.feature


class InBoundTopic(Filter):
    """Passes when the topic is bound to any feature.

    Also injects the resolved feature into handler data: returning a dict from
    a filter merges it into the kwargs the handler receives.
    """

    async def __call__(
        self, message: Message, topic_service: TopicService
    ) -> bool | dict[str, Feature]:
        resolved = topic_service.resolve(message.chat.id, message.message_thread_id)
        if resolved is None:
            return False
        return {"feature": resolved}


class InUnboundTopic(Filter):
    """Passes when the message is in a forum topic with no feature bound."""

    async def __call__(self, message: Message, topic_service: TopicService) -> bool:
        if message.message_thread_id is None:
            return False
        return topic_service.resolve(message.chat.id, message.message_thread_id) is None
