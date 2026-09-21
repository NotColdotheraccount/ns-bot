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
from app.services.ops_service import OpsService, sqlite_path
from app.services.scheduler_service import SchedulerService
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """The database would be written somewhere that does not survive redeploys."""


def prepare_database_path(database_url: str) -> Path | None:
    """Create the database folder, and refuse to run on a disposable disk.

    A container's own filesystem is wiped on every redeploy. If bot.db lives
    there, every push silently erases bindings, check-ins and — worst — the
    record of which letters were delivered, so they would all be sent again.
    Nothing would error; the data would just quietly reset.

    Railway sets RAILWAY_PROJECT_ID on every service and
    RAILWAY_VOLUME_MOUNT_PATH only when a volume is attached. So on Railway we
    require the database file to sit inside the mounted volume, and stop with
    a clear message otherwise. Locally neither variable exists and nothing is
    enforced.
    """
    path = sqlite_path(database_url)
    if path is None:
        return None

    if os.getenv("RAILWAY_PROJECT_ID"):
        volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
        if not volume:
            raise StorageError(
                "Running on Railway with no volume attached. bot.db would be "
                "erased on every redeploy. Add a volume mounted at /data."
            )
        if not path.resolve().is_relative_to(Path(volume).resolve()):
            raise StorageError(
                f"DATABASE_URL points to {path}, outside the volume at {volume}. "
                f"Set DATABASE_URL=sqlite+aiosqlite:///{volume.rstrip('/')}/bot.db"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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

    ops = OpsService(
        database_url=settings.database_url,
        admin_id=settings.admin_telegram_id,
        timezone=settings.tz,
    )

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
        ops=ops,
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
        ops=ops,
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
        await ops.send_startup(bot)

        # start_polling handles SIGTERM, which is how hosting providers stop a
        # container on redeploy: polling stops and the finally block below runs,
        # closing the database cleanly instead of being killed mid-write.
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
        settings = get_settings()
    except ValidationError as exc:
        logger.error("Configuration is invalid:\n%s", exc)
        raise SystemExit(1) from exc

    try:
        db_path = prepare_database_path(settings.database_url)
    except StorageError as exc:
        logger.error("Storage is not persistent: %s", exc)
        raise SystemExit(1) from exc
    logger.info("Database file: %s", db_path.resolve() if db_path else "(not sqlite)")

    try:
        asyncio.run(run())
    except ContentError as exc:
        logger.error("Content is invalid:\n%s", exc)
        raise SystemExit(1) from exc
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested.")


if __name__ == "__main__":
    main()
