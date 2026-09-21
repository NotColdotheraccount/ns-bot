"""Operational safety net: backups, startup notices, heartbeat.

Once the bot is on a server you cannot see it, and during BMT you will not be
able to SSH into anything. Everything here reports to your DM instead, so a
problem is visible from your phone:

  * startup notice   one DM each time the process starts. A redeploy sends one.
                     Several in a row without a redeploy means it is crashing
                     and being restarted, which is the signal to go look.
  * heartbeat        a silent daily DM. If it stops arriving, the bot is down.
  * backup           a weekly copy of bot.db sent to your DM as a file. Free,
                     needs no storage service, and restorable from any device.

Every method here swallows its own errors. Ops messages are a convenience; a
failed backup must never take down the bot she is actually using.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)


def sqlite_path(database_url: str) -> Path | None:
    """Filesystem path of a SQLite database URL, or None for anything else.

    sqlite+aiosqlite:///bot.db        -> bot.db        (relative, three slashes)
    sqlite+aiosqlite:////data/bot.db  -> /data/bot.db  (absolute, four slashes)
    """
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    if url.database == ":memory:":
        return None
    return Path(url.database)


class OpsService:
    """Reports the bot's health to the admin's private chat."""

    def __init__(self, *, database_url: str, admin_id: int, timezone: ZoneInfo) -> None:
        self._db_path = sqlite_path(database_url)
        self._admin_id = admin_id
        self._tz = timezone
        self._started_at = datetime.now(tz=timezone)

    # ----------------------------------------------------------------- status

    def uptime(self) -> str:
        delta = datetime.now(self._tz) - self._started_at
        days, rest = divmod(int(delta.total_seconds()), 86400)
        hours, rest = divmod(rest, 3600)
        minutes = rest // 60
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def db_size(self) -> str:
        if self._db_path is None or not self._db_path.exists():
            return "unknown"
        size = self._db_path.stat().st_size
        return f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    # --------------------------------------------------------------- messages

    async def send_startup(self, bot: Bot) -> None:
        now = datetime.now(self._tz).strftime("%d %b %H:%M")
        await self._dm(bot, f"🟢 <b>Bot started</b> · {now}\ndb: {self.db_size()}")

    async def send_heartbeat(self, bot: Bot, extra: str = "") -> None:
        text = f"💓 still running · up {self.uptime()} · db {self.db_size()}"
        if extra:
            text += f"\n{extra}"
        # Silent: this exists to be noticed when it is MISSING, not to buzz
        # your phone every day.
        await self._dm(bot, text, silent=True)

    async def send_backup(self, bot: Bot) -> bool:
        """Snapshot the database and send it to the admin. True on success."""
        if self._db_path is None or not self._db_path.exists():
            logger.error("Backup skipped — database file not found.")
            return False

        stamp = datetime.now(self._tz).strftime("%Y-%m-%d_%H%M")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / f"bot_backup_{stamp}.db"
            try:
                await asyncio.to_thread(self._snapshot, self._db_path, target)
                await bot.send_document(
                    chat_id=self._admin_id,
                    document=FSInputFile(target),
                    caption=f"🗄 Backup · {stamp.replace('_', ' ')} · {self.db_size()}",
                    disable_notification=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Backup failed | error=%s", type(exc).__name__)
                return False

        logger.info("Backup sent.")
        return True

    # -------------------------------------------------------------- internals

    @staticmethod
    def _snapshot(source: Path, target: Path) -> None:
        """Copy a live SQLite database safely.

        Copying the file with shutil while the bot is writing can capture a
        half-written page and produce a corrupt backup. SQLite's backup API
        takes a consistent snapshot even while other connections are active.
        Runs in a thread because it is blocking I/O.
        """
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    async def _dm(self, bot: Bot, text: str, *, silent: bool = False) -> None:
        try:
            await bot.send_message(
                chat_id=self._admin_id, text=text, disable_notification=silent
            )
        except Exception as exc:  # noqa: BLE001
            # Usually TelegramForbiddenError: you have never opened a DM with
            # the bot, and bots cannot message a user first. Send it /start.
            logger.warning("Admin DM failed | error=%s", type(exc).__name__)
