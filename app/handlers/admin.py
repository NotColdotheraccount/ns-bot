"""Admin commands for managing topic bindings.

Every handler here is gated by IsAdmin, so your girlfriend can never reconfigure
the bot even though she is an authorized user.
"""

from __future__ import annotations

import logging
from datetime import date
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.content.library import ContentError, ContentLibrary
from app.content.letter_library import LetterLibrary
from app.content.memory_library import MemoryLibrary
from app.content.open_when_library import OpenWhenLibrary
from app.database.repositories.settings import CheckInRepository
from app.database.session import Database
from app.features import Feature
from app.filters.admin import IsAdmin
from app.services.letter_service import LetterService
from app.services.ops_service import OpsService
from app.services.scheduler_service import (
    SCHEDULE_DEFAULTS,
    SchedulerService,
    parse_hhmm,
)
from app.services.topic_service import TopicService

logger = logging.getLogger(__name__)

router = Router(name="admin")

# Admin commands are only meaningful in the group, and IsAdmin gates who can
# run them. Applying the filter at router level avoids repeating it per handler.
router.message.filter(IsAdmin())


def _feature_list() -> str:
    """Formatted list of every valid feature identifier."""
    return "\n".join(f"• <code>{feature.value}</code>" for feature in Feature)


def _topic_title(message: Message) -> str | None:
    """Best-effort topic name.

    Telegram only includes the title on the message that *created* the topic,
    so for an ordinary message this is usually None. Purely cosmetic — the
    binding is keyed on the thread ID.
    """
    if message.reply_to_message and message.reply_to_message.forum_topic_created:
        return message.reply_to_message.forum_topic_created.name
    return None


@router.message(Command("bind"))
async def cmd_bind(
    message: Message, command: CommandObject, topic_service: TopicService
) -> None:
    """Bind the current topic to a feature: /bind miss_me"""
    if message.message_thread_id is None:
        await message.answer(
            "⚠️ <b>/bind</b> must be sent inside a forum topic.\n\n"
            "You are in the General topic or a direct message. Open the specific "
            "topic you want to bind and run the command there."
        )
        return

    if not command.args:
        await message.answer(
            "Usage: <code>/bind &lt;feature&gt;</code>\n\n"
            f"<b>Available features:</b>\n{_feature_list()}"
        )
        return

    feature = Feature.parse(command.args)
    if feature is None:
        await message.answer(
            f"❌ Unknown feature: <code>{escape(command.args)}</code>\n\n"
            f"<b>Available features:</b>\n{_feature_list()}"
        )
        return

    previous = topic_service.resolve(message.chat.id, message.message_thread_id)

    await topic_service.bind(
        group_id=message.chat.id,
        thread_id=message.message_thread_id,
        feature=feature,
        topic_title=_topic_title(message),
        user_id=message.from_user.id if message.from_user else 0,
    )

    if previous is not None and previous is not feature:
        note = f"\n\n<i>Replaced previous binding: {previous.label}</i>"
    else:
        note = ""

    await message.answer(
        f"✅ This topic is now <b>{feature.label}</b>\n"
        f"Thread ID: <code>{message.message_thread_id}</code>{note}"
    )


@router.message(Command("unbind"))
async def cmd_unbind(message: Message, topic_service: TopicService) -> None:
    """Remove the binding for the current topic."""
    if message.message_thread_id is None:
        await message.answer("⚠️ <b>/unbind</b> must be sent inside a forum topic.")
        return

    removed = await topic_service.unbind(
        group_id=message.chat.id, thread_id=message.message_thread_id
    )

    if removed is None:
        await message.answer("This topic was not bound to anything.")
        return

    await message.answer(f"🗑 Unbound. This topic no longer handles <b>{removed.label}</b>.")


@router.message(Command("bindings"))
async def cmd_bindings(message: Message, topic_service: TopicService) -> None:
    """List every configured binding, and which features are still unassigned."""
    bindings = topic_service.all_bindings()

    if not bindings:
        await message.answer(
            "No topics are bound yet.\n\n"
            "Open a topic and run <code>/bind &lt;feature&gt;</code> to begin."
        )
        return

    lines = ["<b>Topic bindings</b>", ""]
    for thread_id, feature, title in bindings:
        suffix = f" — {escape(title)}" if title else ""
        lines.append(f"{feature.label} → thread <code>{thread_id}</code>{suffix}")

    bound_features = {feature for _thread, feature, _title in bindings}
    missing = [feature for feature in Feature if feature not in bound_features]
    if missing:
        lines.append("")
        lines.append(f"<i>Not yet bound ({len(missing)}):</i>")
        lines.append(", ".join(f"<code>{feature.value}</code>" for feature in missing))

    await message.answer("\n".join(lines))


@router.message(Command("content"))
async def cmd_content(
    message: Message,
    content_library: ContentLibrary,
    memory_library: MemoryLibrary,
) -> None:
    """Summarise the loaded content library."""
    stats = content_library.stats()
    if not stats:
        await message.answer(
            "No content loaded.\n\n"
            "Add YAML files to <code>data/content/</code> and run "
            "<code>/reloadcontent</code>."
        )
        return

    lines = ["<b>Content library</b>", ""]
    for kind, count in sorted(stats.items()):
        lines.append(f"{kind}: <b>{count}</b>")
    lines.append(f"\nTotal: <b>{sum(stats.values())}</b>")
    lines.append(f"Memories: <b>{memory_library.count}</b>")

    missing = content_library.missing_files
    if missing:
        lines.append(f"\n⚠️ <i>{len(missing)} item(s) skipped — file not found:</i>")
        for entry in missing[:10]:
            lines.append(f"<code>{escape(entry)}</code>")
        if len(missing) > 10:
            lines.append(f"<i>...and {len(missing) - 10} more</i>")

    await message.answer("\n".join(lines))


@router.message(Command("reloadcontent"))
async def cmd_reload_content(
    message: Message,
    content_library: ContentLibrary,
    memory_library: MemoryLibrary,
    letter_library: LetterLibrary,
    open_when_library: OpenWhenLibrary,
) -> None:
    """Re-read the YAML files without restarting the bot.

    Send history is untouched: it lives in SQLite keyed on content id, and this
    only reloads the authored definitions.
    """
    try:
        content_library.load()
        memory_library.load()
        letter_library.load()
        open_when_library.load()
    except ContentError as exc:
        logger.warning("Content reload failed.")
        # The exception text names the offending file and field, which is
        # exactly what you need to fix it — and contains no private content.
        await message.answer(f"❌ <b>Reload failed</b>\n\n<pre>{escape(str(exc))}</pre>")
        return

    stats = content_library.stats()
    missing = content_library.missing_files
    suffix = f"\n⚠️ {len(missing)} skipped (file missing)" if missing else ""
    await message.answer(
        f"♻️ Reloaded <b>{sum(stats.values())}</b> content items "
        f"and <b>{memory_library.count}</b> memories "
        f"and <b>{letter_library.count}</b> letters "
        f"and <b>{open_when_library.count}</b> open-when.{suffix}"
    )


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, scheduler: SchedulerService) -> None:
    """Show current schedule times and their destination topics."""
    times = await scheduler.current_schedule()
    lines = ["<b>Schedule</b> <i>(Asia/Singapore)</i>", ""]

    # Must cover every key in SCHEDULE_DEFAULTS. A missing entry here crashed
    # this command once `letters` was added as a fourth scheduled job.
    destinations = {
        "morning": Feature.GOOD_MORNING,
        "checkin": Feature.DAILY_CHECKIN,
        "goodnight": Feature.GOODNIGHT,
        "letters": Feature.LETTERS,
    }
    for name, value in times.items():
        feature = destinations.get(name)
        if feature is None:
            continue
        thread = scheduler.thread_for(feature)
        target = f"thread <code>{thread}</code>" if thread else "⚠️ <b>not bound</b>"
        lines.append(f"{name}: <code>{value}</code> → {target}")

    lines.append("")
    lines.append("Change with <code>/setschedule morning 07:30</code>")
    await message.answer("\n".join(lines))


@router.message(Command("setschedule"))
async def cmd_set_schedule(
    message: Message, command: CommandObject, scheduler: SchedulerService
) -> None:
    """/setschedule morning 07:30 — change a time and reload jobs live."""
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer(
            "Usage: <code>/setschedule &lt;morning|checkin|goodnight|letters&gt; &lt;HH:MM&gt;</code>"
        )
        return

    name, value = parts[0].lower(), parts[1]
    if f"schedule.{name}" not in SCHEDULE_DEFAULTS:
        await message.answer("Job must be one of: morning, checkin, goodnight, letters")
        return
    if parse_hhmm(value) is None:
        await message.answer("Time must be 24-hour <code>HH:MM</code>, e.g. <code>07:30</code>")
        return

    await scheduler.set_schedule(name, value)
    await message.answer(f"✅ {name} is now <code>{value}</code> (Singapore time).")


@router.message(Command("testmorning"))
async def cmd_test_morning(message: Message, scheduler: SchedulerService) -> None:
    await scheduler.send_morning()
    await message.answer("Sent (check the Good Morning topic).")


@router.message(Command("testgoodnight"))
async def cmd_test_goodnight(message: Message, scheduler: SchedulerService) -> None:
    await scheduler.send_goodnight()
    await message.answer("Sent (check the Goodnight topic).")


@router.message(Command("testcheckin"))
async def cmd_test_checkin(message: Message, scheduler: SchedulerService) -> None:
    await scheduler.send_checkin()
    await message.answer("Sent (check the Daily Check-In topic).")


@router.message(Command("checkins"))
async def cmd_checkins(message: Message, database: Database) -> None:
    """Recent check-in answers."""
    async with database.session() as session:
        rows = await CheckInRepository(session).recent(14)

    if not rows:
        await message.answer("No check-ins recorded yet.")
        return

    emoji = {"amazing": "🥰", "good": "😊", "okay": "😐", "bad": "😔", "terrible": "😭"}
    lines = ["<b>Recent check-ins</b>", ""]
    for row in rows:
        lines.append(f"{row.local_date}  {emoji.get(row.mood, '')} {row.mood}")
    await message.answer("\n".join(lines))


@router.message(Command("letters"))
async def cmd_letters(message: Message, letter_service: LetterService) -> None:
    """Show letter status: enlistment date, delivered, pending, upcoming."""
    enlistment = await letter_service.enlistment_date()
    today = letter_service.today()
    pending = await letter_service.pending()
    delivered = await letter_service.delivered_count()
    upcoming = letter_service.upcoming(today, enlistment)

    elapsed = (today - enlistment).days
    when = f"day {elapsed}" if elapsed >= 0 else f"in {-elapsed} days"

    lines = [
        "<b>Letters</b>",
        "",
        f"Enlistment: <code>{enlistment.isoformat()}</code> ({when})",
        f"Total written: <b>{letter_service.count}</b>",
        f"Delivered: <b>{delivered}</b>",
        f"Pending now: <b>{len(pending)}</b>",
    ]
    if pending:
        lines.append("")
        lines.append("<i>Waiting to send:</i>")
        for letter in pending[:5]:
            lines.append(f"  #{letter.number} — {escape(letter.title)}")
    if upcoming:
        lines.append("")
        lines.append("<i>Upcoming:</i>")
        for letter in upcoming:
            lines.append(
                f"  {letter.due_on(enlistment).isoformat()} — #{letter.number} {escape(letter.title)}"
            )
    lines.append("")
    lines.append("<code>/setenlistment 2026-10-01</code> · <code>/testletter 1</code>")
    await message.answer("\n".join(lines))


@router.message(Command("setenlistment"))
async def cmd_set_enlistment(
    message: Message, command: CommandObject, letter_service: LetterService
) -> None:
    """/setenlistment 2026-10-01 — all `day:` letters are relative to this."""
    raw = (command.args or "").strip()
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        await message.answer(
            "Usage: <code>/setenlistment YYYY-MM-DD</code>\n"
            "e.g. <code>/setenlistment 2026-10-01</code>"
        )
        return

    await letter_service.set_enlistment_date(value)
    pending = await letter_service.pending()
    await message.answer(
        f"✅ Enlistment set to <code>{value.isoformat()}</code>.\n"
        f"{len(pending)} letter(s) now pending."
    )


@router.message(Command("testletter"))
async def cmd_test_letter(
    message: Message,
    command: CommandObject,
    bot: Bot,
    letter_service: LetterService,
    topic_service: TopicService,
) -> None:
    """Preview a letter without marking it delivered."""
    raw = (command.args or "").strip()
    if not raw.isdigit():
        await message.answer("Usage: <code>/testletter 1</code>")
        return

    letter = letter_service.by_number(int(raw))
    if letter is None:
        await message.answer(f"No letter #{raw}.")
        return

    thread_id = topic_service.thread_for(Feature.LETTERS)
    if thread_id is None:
        await message.answer("⚠️ No topic is bound to <code>letters</code> yet.")
        return

    await letter_service.send(bot, letter, thread_id=thread_id)
    await message.answer(
        f"Preview of #{letter.number} sent. <i>Not</i> marked as delivered."
    )


@router.message(Command("sendletters"))
async def cmd_send_letters(
    message: Message, bot: Bot, letter_service: LetterService
) -> None:
    """Run the letter dispatcher now, exactly as the daily job would."""
    count = await letter_service.dispatch_due(bot)
    if count == 0:
        await message.answer("Nothing due right now.")
        return
    await message.answer(f"Delivered {count} letter(s).")


@router.message(Command("backup"))
async def cmd_backup(message: Message, bot: Bot, ops: OpsService | None) -> None:
    """Send a database backup to the admin's DM right now.

    Always goes to your DM, never to the chat the command was typed in: the
    file contains her check-ins and everything the bot has recorded.
    """
    if ops is None:
        await message.answer("Ops service not configured.")
        return
    ok = await ops.send_backup(bot)
    if message.chat.type != "private" or not ok:
        await message.answer("🗄 Backup sent to your DM." if ok else "❌ Backup failed — check logs.")


@router.message(Command("health"))
async def cmd_health(
    message: Message,
    scheduler: SchedulerService,
    letter_service: LetterService,
    ops: OpsService | None,
) -> None:
    """Uptime, storage, and when each job will next run."""
    lines = ["<b>Health</b>", ""]
    if ops is not None:
        lines.append(f"Uptime: <code>{ops.uptime()}</code>")
        lines.append(f"Database: <code>{ops.db_path}</code> ({ops.db_size()})")

    pending = await letter_service.pending()
    delivered = await letter_service.delivered_count()
    lines.append(f"Letters: {delivered} delivered · {len(pending)} pending")

    lines.append("")
    lines.append("<b>Next runs</b> <i>(Singapore)</i>")
    for job_id, next_run in scheduler.next_runs():
        when = next_run.strftime("%a %d %b %H:%M") if next_run else "paused"
        lines.append(f"<code>{job_id:<10}</code> {when}")

    await message.answer("\n".join(lines))
