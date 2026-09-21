"""System commands: liveness check, ID discovery, and access reporting.

Everything here is already behind the authorization middleware, so only you and
your girlfriend can reach these handlers at all.
"""

from __future__ import annotations

import logging
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.filters.admin import IsAdmin

logger = logging.getLogger(__name__)

router = Router(name="system")


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    """Confirm the bot is alive and receiving updates."""
    logger.info("ping received | chat_type=%s", message.chat.type)
    await message.answer("pong ✅")


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    """Report the identifiers for the current chat and topic.

    Still useful after bootstrap: from Stage 3 you will use it to sanity-check
    thread IDs when binding features to topics.
    """
    user = message.from_user
    chat = message.chat

    # message_thread_id is None in DMs and in a forum's "General" topic.
    thread_id = message.message_thread_id
    thread_display = str(thread_id) if thread_id is not None else "None (DM or General)"

    lines = [
        "<b>Telegram identifiers</b>",
        "",
        f"User ID: <code>{user.id if user else 'unknown'}</code>",
        f"Chat ID: <code>{chat.id}</code>",
        f"Chat type: <code>{chat.type}</code>",
        f"Chat title: {escape(chat.title) if chat.title else '—'}",
        f"Forum enabled: <code>{bool(chat.is_forum)}</code>",
        f"Thread ID: <code>{thread_display}</code>",
    ]

    logger.info(
        "id requested | chat_type=%s is_forum=%s has_thread=%s",
        chat.type,
        bool(chat.is_forum),
        thread_id is not None,
    )

    await message.answer("\n".join(lines))


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, is_admin: bool) -> None:
    """Report how the bot sees the caller.

    `is_admin` arrives as a plain argument because the authorization
    middleware placed it in the handler data. aiogram inspects the function
    signature and injects matching keys automatically.
    """
    role = "admin 🛠" if is_admin else "authorized user ❤️"
    await message.answer(f"You are recognised as: <b>{role}</b>")


@router.message(Command("status"), IsAdmin())
async def cmd_status(message: Message, settings: Settings) -> None:
    """Admin-only summary of the running configuration.

    Deliberately reports whether secrets are *present*, never their values —
    this reply lives in a Telegram chat that is backed up to Telegram's servers.
    """
    lines = [
        "<b>Bot status</b>",
        "",
        f"Timezone: <code>{settings.timezone}</code>",
        f"Authorized users: <code>{len(settings.authorized_user_ids)}</code>",
        f"Group ID: <code>{settings.telegram_group_id}</code>",
        f"Claude key configured: <code>{settings.claude_api_key is not None}</code>",
    ]
    await message.answer("\n".join(lines))
