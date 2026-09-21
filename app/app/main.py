"""Application entry point.

Run with:  python -m app.main
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.content.letter_library import LetterLibrary
from app.content.library import ContentError, ContentLibrary
from app.content.memory_library import MemoryLibrary
from app.content.open_when_library import OpenWhenLibrary
from app.database.session import Database
from app.logging_setup import setup_logging
from app.services.content_selector import ContentSelector
from app.services.delivery import ContentDelivery
from app.services.letter_service import LetterService
from app.services.media_service import MediaService
from app.services.memory_service import MemoryService
from app.services.scheduler_service import SchedulerService
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()

    # Content is loaded from files relative to the project root, so the bot
    # behaves the same on your laptop and inside a container.
    project_root = Path(__file__).resolve().parent.parent

    # --- database -----------------------------------------------------------
    # Startup order matters: the schema must exist before bindings are loaded,
    # and bindings must be cached before the first update is handled.
    database = Database(settings.database_url)
    await database.create_all()

    topic_service = TopicService(database)
    await topic_service.load()

    # --- content ------------------------------------------------------------
    content_library = ContentLibrary(
        content_dir=project_root / "data" / "content",
        media_dir=project_root / "media",
    )
    content_library.load()

    memory_library = MemoryLibrary(
        memories_dir=project_root / "data" / "memories",
        media_dir=project_root / "media",
    )
    memory_library.load()

    letter_library = LetterLibrary(
        letters_dir=project_root / "data" / "letters",
        media_dir=project_root / "media",
    )
    letter_library.load()

    open_when_library = OpenWhenLibrary(
        directory=project_root / "data" / "open_when",
        media_dir=project_root / "media",
    )
    open_when_library.load()

    # --- services -----------------------------------------------------------
    content_selector = ContentSelector(content_library, database)
    media_service = MediaService(content_library, database)
    delivery = ContentDelivery(content_selector, media_service)
    memory_service = MemoryService(memory_library, database)

    bot = create_bot(settings.telegram_bot_token)

    letter_service = LetterService(
        library=letter_library,
        database=database,
        topic_service=topic_service,
        timezone=settings.tz,
        group_id=settings.telegram_group_id,
    )

    scheduler = SchedulerService(
        bot=bot,
        database=database,
        topic_service=topic_service,
        selector=content_selector,
        media=media_service,
        timezone=settings.tz,
        group_id=settings.telegram_group_id,
        letter_service=letter_service,
    )

    dispatcher = create_dispatcher(
        settings,
        topic_service,
        content_library,
        content_selector,
        delivery,
        memory_library,
        memory_service,
        scheduler,
        database,
        letter_service,
        letter_library,
        open_when_library,
    )

    # --- run ----------------------------------------------------------------
    try:
        me = await bot.get_me()
        logger.info("Starting @%s (id=%s) | tz=%s", me.username, me.id, settings.timezone)
        logger.info(
            "Access locked | authorized_users=%s group_id=%s",
            len(settings.authorized_user_ids),
            settings.telegram_group_id,
        )

        # Clear any webhook left over from earlier experiments. Telegram allows
        # either webhooks or long polling, never both, and a stale webhook makes
        # polling silently receive nothing.
        await bot.delete_webhook(drop_pending_updates=True)

        await scheduler.start()
        await dispatcher.start_polling(bot)
    finally:
        await scheduler.shutdown()
        await bot.session.close()
        await database.dispose()
        logger.info("Bot stopped.")


def main() -> None:
    load_dotenv()
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    try:
        get_settings()
    except ValidationError as exc:
        logger.error("Configuration is invalid:\n%s", exc)
        raise SystemExit(1) from exc

    try:
        asyncio.run(run())
    except ContentError as exc:
        logger.error("Content is invalid:\n%s", exc)
        raise SystemExit(1) from exc
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested.")


if __name__ == "__main__":
    main()
