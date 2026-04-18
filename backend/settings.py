from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from .models import Location

logger = logging.getLogger(__name__)

load_dotenv()

MAX_DAYS_RANGE = 16
ALLOWED_ORIGINS = ["http://localhost:3000"]

FORECAST_WEATHER_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_WEATHER_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
AIR_QUALITY_ENDPOINT = "https://air-quality-api.open-meteo.com/v1/air-quality"

DEFAULT_DAILY_LOCATION = Location(
    name="Copenhagen",
    latitude=55.6761,
    longitude=12.5683,
)

DEV_TAG = os.getenv("DEV_TAG", "dev")


def get_docs_url() -> str | None:
    return os.getenv("DOCS_URL", None)

def get_discord_webhook_url() -> str | None:
    return os.getenv("DISCORD_WEBHOOK_URL")


def get_discord_public_key() -> str | None:
    return os.getenv("DISCORD_PUBLIC_KEY")


def get_discord_bot_token() -> str | None:
    return os.getenv("DISCORD_BOT_TOKEN")


def get_discord_application_id() -> str | None:
    return os.getenv("DISCORD_APPLICATION_ID")


def get_discord_guild_id() -> str | None:
    return os.getenv("DISCORD_GUILD_ID")


def _discord_slash_builtin_ephemeral_defaults() -> dict[str, bool]:
    return {"2_hours": True, "4_hours": True, "weather": False}


def get_discord_slash_ephemeral_defaults() -> dict[str, bool]:
    raw = os.getenv("DISCORD_SLASH_VISIBILITY_DEFAULTS_JSON")
    if not raw:
        return _discord_slash_builtin_ephemeral_defaults()
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid DISCORD_SLASH_VISIBILITY_DEFAULTS_JSON; using built-in defaults")
        return _discord_slash_builtin_ephemeral_defaults()
    if not isinstance(parsed, dict):
        return _discord_slash_builtin_ephemeral_defaults()
    out = _discord_slash_builtin_ephemeral_defaults()
    for key, value in parsed.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("private", "ephemeral", "true", "1", "yes"):
                out[key] = True
            elif lowered in ("public", "channel", "false", "0", "no"):
                out[key] = False
    return out


def get_discord_slash_reply_ephemeral(command_name: str) -> bool:
    """Whether the deferred slash reply for this command should be ephemeral (developer config only)."""
    return get_discord_slash_ephemeral_defaults().get(command_name, True)


def get_cron_shared_secret() -> str | None:
    return os.getenv("CRON_SHARED_SECRET")


def get_langfuse_public_key() -> str | None:
    return os.getenv("LANGFUSE_PUBLIC_KEY")


def get_langfuse_secret_key() -> str | None:
    return os.getenv("LANGFUSE_SECRET_KEY")


def get_langfuse_base_url() -> str | None:
    return os.getenv("LANGFUSE_BASE_URL")
