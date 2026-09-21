"""Factory functions for the Bot and Dispatcher.

Kept separate from main.py so tests can build a Dispatcher without starting
the polling loop or touching the network.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Settings
from app.database.session import Database
from app.content.library import ContentLibrary
from app.content.letter_library import LetterLibrary
from app.content.memory_library import MemoryLibrary
from app.content.open_when_library import OpenWhenLibrary
from app.handlers import (
    admin,
    bad_day,
    checkin,
    demo,
    fallback,
    memories,
    miss_me,
    open_when,
    reassurance,
    songs,
    system,
    voice,
)
from app.middleware.authorization import AuthorizationMiddleware
from app.services.content_selector import ContentSelector
from app.services.delivery import ContentDelivery
from app.services.memory_service import MemoryService
from app.services.letter_service import LetterService
from app.services.scheduler_service import SchedulerService
from app.services.topic_service import TopicService


def create_bot(token: str) -> Bot:
    """Build the Bot instance.

    HTML is chosen over MarkdownV2 as the default parse mode because MarkdownV2
    requires escaping a long list of characters (including '.', '-' and '!'),
    which is painful for the kind of natural, emoji-heavy text this bot sends.
    """
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    settings: Settings,
    topic_service: TopicService,
    content_library: ContentLibrary,
    content_selector: ContentSelector,
    delivery: ContentDelivery,
    memory_library: MemoryLibrary,
    memory_service: MemoryService,
    scheduler: SchedulerService,
    database: Database,
    letter_service: LetterService,
    letter_library: LetterLibrary,
    open_when_library: OpenWhenLibrary,
) -> Dispatcher:
    """Build the Dispatcher, install middleware, and register routers.

    MemoryStorage is fine here: FSM state in this bot is short-lived (things
    like 'she just tapped a Bad Day button'). Losing it on restart is harmless,
    and anything that must survive restarts goes in SQLite instead.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())

    # Registered as an *outer* middleware on the update observer so it runs
    # before any filter is evaluated. An inner middleware would run only after
    # a handler had already been matched, which wastes work on traffic we are
    # about to discard.
    dispatcher.update.outer_middleware(AuthorizationMiddleware(settings))

    # Workflow data is injected into every handler AND every filter that names
    # it as an argument. This is how BoundTo reaches topic_service without a
    # module-level global.
    dispatcher["topic_service"] = topic_service
    dispatcher["content_library"] = content_library
    dispatcher["content_selector"] = content_selector
    dispatcher["delivery"] = delivery
    dispatcher["memory_library"] = memory_library
    dispatcher["memory_service"] = memory_service
    dispatcher["scheduler"] = scheduler
    dispatcher["database"] = database
    dispatcher["letter_service"] = letter_service
    dispatcher["letter_library"] = letter_library
    dispatcher["open_when_library"] = open_when_library

    # ORDER MATTERS. aiogram tries routers in registration order and stops at
    # the first match, so specific routers come before catch-all ones:
    #   1. system   — /ping, /id, /whoami, /status
    #   2. admin    — /bind, /unbind, /bindings
    #   3. features — each matches only its own bound topic
    #   4. demo     — any BOUND topic with no feature handler yet
    #   5. fallback — any text in an UNBOUND topic (must be last)
    dispatcher.include_router(system.router)
    dispatcher.include_router(admin.router)

    dispatcher.include_router(miss_me.router)
    dispatcher.include_router(voice.router)
    dispatcher.include_router(songs.router)
    dispatcher.include_router(reassurance.router)
    dispatcher.include_router(bad_day.router)
    dispatcher.include_router(memories.router)
    dispatcher.include_router(open_when.router)
    dispatcher.include_router(checkin.router)

    dispatcher.include_router(demo.router)
    dispatcher.include_router(fallback.router)

    return dispatcher
