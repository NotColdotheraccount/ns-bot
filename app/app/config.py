"""Application configuration.

Settings are loaded from environment variables (and a local .env file) and
validated once at startup. If something is wrong we want to fail immediately
with a clear message, not three hours later inside a scheduled job.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    telegram_bot_token: str

    # As of Stage 2 these are mandatory. The bot enforces authorization using
    # them, so starting without them would mean starting wide open.
    admin_telegram_id: int
    girlfriend_telegram_id: int
    telegram_group_id: int

    # --- Claude (used from Stage 15) ---
    claude_api_key: str | None = None

    # --- Runtime ---
    database_url: str = "sqlite+aiosqlite:///bot.db"
    timezone: str = "Asia/Singapore"
    log_level: str = "INFO"

    @field_validator("claude_api_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Treat an empty .env entry as 'not set'.

        A line like `CLAUDE_API_KEY=` is present with the value "", not absent.
        mode="before" runs ahead of type coercion, which is the only place a
        value that would fail conversion can be intercepted.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator(
        "admin_telegram_id",
        "girlfriend_telegram_id",
        "telegram_group_id",
        mode="before",
    )
    @classmethod
    def _require_id(cls, value: object, info: ValidationInfo) -> object:
        """Turn a blank required ID into an actionable error message.

        Without this, a blank line produces "unable to parse string as an
        integer", which does not tell you what to actually do about it.
        """
        if isinstance(value, str) and value.strip() == "":
            raise ValueError(
                f"{(info.field_name or '').upper()} is blank in .env. "
                "Send /id to the bot (in a DM for user IDs, inside a group "
                "topic for the group ID) to discover the correct value."
            )
        return value

    @field_validator("telegram_bot_token")
    @classmethod
    def _validate_token(cls, value: str) -> str:
        # Telegram tokens look like "<bot_id>:<secret>". Catching an obviously
        # malformed token here gives a much better error than a 401 from the API.
        if ":" not in value or not value.split(":", 1)[0].isdigit():
            raise ValueError(
                "TELEGRAM_BOT_TOKEN looks malformed. "
                "Expected something like '123456789:AA...' from @BotFather."
            )
        return value

    @field_validator("telegram_group_id")
    @classmethod
    def _validate_group_id(cls, value: int) -> int:
        # Supergroup IDs are always negative. A positive number here almost
        # always means someone pasted a user ID by mistake.
        if value >= 0:
            raise ValueError(
                "TELEGRAM_GROUP_ID must be negative (supergroups look like "
                "-1001234567890). You may have pasted a user ID."
            )
        return value

    @field_validator("admin_telegram_id", "girlfriend_telegram_id")
    @classmethod
    def _validate_user_id(cls, value: int, info: ValidationInfo) -> int:
        # User IDs are always positive. A negative value means a chat ID was
        # pasted into a user field.
        if value <= 0:
            raise ValueError(
                f"{(info.field_name or '').upper()} must be a positive user ID. "
                "A negative value is a chat/group ID, not a user ID."
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown timezone {value!r}. On Windows this usually means the "
                "'tzdata' package is missing — run: pip install tzdata"
            ) from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @model_validator(mode="after")
    def _ids_must_differ(self) -> Settings:
        # Almost always a copy-paste slip. If they matched, admin-only commands
        # would silently become available to her.
        if self.admin_telegram_id == self.girlfriend_telegram_id:
            raise ValueError(
                "ADMIN_TELEGRAM_ID and GIRLFRIEND_TELEGRAM_ID are the same value. "
                "Each person needs their own Telegram user ID."
            )
        return self

    @property
    def tz(self) -> ZoneInfo:
        """The configured timezone as a usable object."""
        return ZoneInfo(self.timezone)

    @property
    def authorized_user_ids(self) -> frozenset[int]:
        """Every user allowed to interact with the bot."""
        return frozenset({self.admin_telegram_id, self.girlfriend_telegram_id})

    def is_admin(self, user_id: int) -> bool:
        """True if the given Telegram user ID is the admin."""
        return user_id == self.admin_telegram_id


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton settings object.

    Cached so the .env file is parsed once. Using a function instead of a
    module-level constant keeps tests able to clear the cache and inject
    different configuration.
    """
    return Settings()
