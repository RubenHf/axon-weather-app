from .models import Location
import os

from dotenv import load_dotenv

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


def get_discord_webhook_url() -> str | None:
    return os.getenv("DISCORD_WEBHOOK_URL")


def get_cron_shared_secret() -> str | None:
    return os.getenv("CRON_SHARED_SECRET")
