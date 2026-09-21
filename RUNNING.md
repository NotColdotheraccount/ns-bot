# Running the bot

## Start it

```powershell
cd C:\Users\2006a\Projects\telegram-bot
.\.venv\Scripts\Activate.ps1
python -m app.main
```

If the prompt already shows `(.venv)`, skip line 2.

**Working when you see:**
```
Run polling for bot @ItsAqeefAIbot
```

Leave the terminal open. The bot only responds while it's running.

## Stop it

`Ctrl+C` (press twice if the first doesn't take).

## Restart after editing code

```
Ctrl+C  →  ↑  →  Enter
```

Any change to a `.py` file needs a restart. No hot reload.

**Exception:** editing YAML in `data/` only needs `/reloadcontent` in Telegram — no restart.

---

## Healthy startup

```
Database schema ready.
Loaded 6 topic bindings (0 skipped).
Loaded 20 content items.
Loaded 3 memories.
Loaded 4 letters.
Starting @ItsAqeefAIbot | tz=Asia/Singapore
Access locked | authorized_users=2 group_id=-100...
Scheduler started | tz=Asia/Singapore
  job morning    next run: ... +08:00
  job letters    next run: ... +08:00
  job checkin    next run: ... +08:00
  job goodnight  next run: ... +08:00
Run polling for bot @ItsAqeefAIbot
```

Check the job times end in **`+08:00`**. If they say `+00:00`, the timezone is wrong and scheduled messages will arrive 8 hours off.

`media file(s) not found` warnings are fine — those are placeholder paths.

---

## Admin commands

Only you can run these. Send them in the group.

### Setup
| | |
|---|---|
| `/bind <feature>` | bind current topic to a feature |
| `/unbind` | remove this topic's binding |
| `/bindings` | list all bindings + what's unbound |
| `/id` | chat ID, thread ID, forum status |

### Content
| | |
|---|---|
| `/content` | counts + missing media files |
| `/reloadcontent` | re-read YAML without restarting |

### Schedule
| | |
|---|---|
| `/schedule` | times + destination topics |
| `/setschedule morning 07:30` | change a time, live |
| `/testmorning` `/testgoodnight` `/testcheckin` | fire a job now |
| `/checkins` | last 14 answers |

### Letters
| | |
|---|---|
| `/letters` | delivered, pending, upcoming |
| `/setenlistment 2026-10-01` | set the anchor date |
| `/testletter 1` | preview (does **not** mark delivered) |
| `/sendletters` | run the dispatcher now |

### Other
| | |
|---|---|
| `/status` | config summary |
| `/whoami` | admin or not |
| `/ping` | alive check |

---

## Adding content

| Type | File | Media folder |
|---|---|---|
| Reassurance, voice, songs | `data/content/*.yaml` | `media/voice/`, `media/songs/` |
| Memories | `data/memories/*.yaml` | `media/photos/` |
| Letters | `data/letters/*.yaml` | `media/` |

`file:` paths are relative to `media/`, so `voice/hello.ogg` → `media/voice/hello.ogg`.

Then `/reloadcontent`.

**Never reuse an `id`.** Send history is keyed on it.

### Tag vocabulary

```
general comfort reassurance missing_me bad_day stress overthinking
insecurity sleep argument frustrated sad motivation love funny random
morning goodnight
```

Bad Day buttons map to: `sad` `stress` `overthinking` `missing_me` `frustrated` `comfort`

---

## Voice notes

Record in Telegram **Saved Messages** → right-click on Desktop → Save As → `media/voice/`.

Must be `.ogg`. An mp3 sent as `kind: voice` is rejected by Telegram — use `kind: audio` for those.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named 'app'` | Wrong folder, or used `python app/main.py`. Use `python -m app.main` from the project root. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Bot ignores you | Wrong `ADMIN_TELEGRAM_ID`. The terminal logs the ID it actually saw. |
| Silent in a topic | `/bindings` — probably not bound |
| Job times show `+00:00` | Timezone bug — tell Claude |
| `Loaded 0 bindings` | Running from the wrong folder; a second `bot.db` got created |
| Nothing at all, no errors | Stale webhook. Restart — `delete_webhook` runs on boot. |

---

## Don't break these

- **`.env` is gitignored.** Never commit it. If the token leaks, revoke via BotFather.
- **Keep the repo private** — it holds your recordings and everything you write her.
- **`bot.db` holds all state** — bindings, check-ins, send history, letter delivery. Back it up before deploying.
- **Deleting a topic** orphans its binding. Rename freely; don't delete.

---

## On Railway (after deploying)

### Only ONE copy may run
Two copies polling the same token fight each other (`TelegramConflictError`).
Once Railway is live, **don't start the bot on your laptop** — test locally only
after pausing Railway, or with a second test bot token.

### Updating content
Content is baked into each deploy, so on Railway `/reloadcontent` does **not**
pick up edits. Instead:

1. Edit YAML or upload media on github.com (works from your phone)
2. Commit → Railway rebuilds and restarts automatically (~1–2 min)

Avoid pushing within a few minutes of 08:00 / 21:00 / 23:00 — a restart at that
moment skips that day's message.

### Ops commands
| | |
|---|---|
| `/health` | uptime, database location, next run of every job |
| `/backup` | database snapshot sent to your DM now |

### What arrives in your DM
| Message | Meaning |
|---|---|
| 🟢 Bot started | Process started. One per deploy is normal. **Several without a deploy = crash loop.** |
| 💓 still running (silent, 12:00 daily) | Healthy. **If it stops arriving, the bot is down.** |
| 🗄 Backup (silent, Sun 03:00) | Weekly `bot.db` copy. Keep the latest few. |

### Restoring a backup
Download the backup file from your DM, rename it `bot.db`, and upload it to the
volume at `/data/bot.db` (ask Claude for the steps if you ever need this).

### Railway troubleshooting
| Log says | Fix |
|---|---|
| `Storage is not persistent … no volume attached` | Add a volume mounted at `/data` |
| `… outside the volume` | `DATABASE_URL=sqlite+aiosqlite:////data/bot.db` (four slashes) |
| `Configuration is invalid` | A variable is missing — check the Variables tab |
| `TelegramConflictError` | The bot is also running somewhere else. Stop your laptop copy. |
| No 🟢 DM at startup | Send the bot any message in a DM once — bots can't message you first |
