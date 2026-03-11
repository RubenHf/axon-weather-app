from datetime import datetime, timezone
import json
import logging
import re

import httpx
from .baml_client import b
from fastapi import HTTPException

from .models import WeatherRequest
from .settings import (
    ARCHIVE_WEATHER_ENDPOINT,
    DEFAULT_DAILY_LOCATION,
    FORECAST_WEATHER_ENDPOINT,
    MAX_DAYS_RANGE,
    get_cron_shared_secret,
    get_discord_webhook_url,
)

logger = logging.getLogger(__name__)


def build_weather_endpoint(query_type: str) -> str:
    if query_type == "archive":
        return ARCHIVE_WEATHER_ENDPOINT
    if query_type == "forecast":
        return FORECAST_WEATHER_ENDPOINT
    logger.error("Invalid query type: %s", query_type)
    raise HTTPException(status_code=400, detail="Invalid query type")


def validate_weather_api_plan_dates(weather_api_plans: list) -> None:
    for plan in weather_api_plans:
        try:
            start = datetime.strptime(plan.start_date, "%Y-%m-%d")
            end = datetime.strptime(plan.end_date, "%Y-%m-%d")
            days_diff = (end - start).days

            logger.debug(
                "Validating date range: %s to %s (%s days)",
                plan.start_date,
                plan.end_date,
                days_diff,
            )

            if days_diff > MAX_DAYS_RANGE:
                logger.warning(
                    "Date range too wide: %s days for plan %s to %s",
                    days_diff,
                    plan.start_date,
                    plan.end_date,
                )
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Date range too wide: {plan.start_date} to {plan.end_date} ({days_diff} days). "
                        f"Maximum allowed is {MAX_DAYS_RANGE} days per request. "
                        "For historical comparisons, please use multiple separate requests for the same date across different years."
                    ),
                )
        except ValueError as exc:
            logger.error("Invalid date format in plan: %s", str(exc))
            raise HTTPException(status_code=400, detail=f"Invalid date format: {str(exc)}")


async def fetch_weather_api_data(request: WeatherRequest) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info("Extracting API parameters for question: %s", request.question)
    weather_api_plans = b.ExtractOpenMeteoHistoricalRequest(request.question, today)
    validate_weather_api_plan_dates(weather_api_plans)

    all_api_data: list[dict] = []
    logger.info("Making %s API calls to Open-Meteo API", len(weather_api_plans))

    async with httpx.AsyncClient() as client:
        for plan in weather_api_plans:
            api_params = plan.model_dump()
            query_type = api_params.pop("query_type")
            api_endpoint = build_weather_endpoint(query_type)
            logger.info(
                "Calling %s API: %s for dates %s to %s",
                query_type,
                api_endpoint,
                api_params.get("start_date"),
                api_params.get("end_date"),
            )

            response = await client.get(
                api_endpoint,
                params={
                    **api_params,
                    "latitude": request.location.latitude,
                    "longitude": request.location.longitude,
                },
            )
            response.raise_for_status()

            all_api_data.append(
                {
                    "query_type": query_type,
                    "date_range": f"{api_params.get('start_date')} to {api_params.get('end_date')}",
                    "data": response.json(),
                }
            )

    return all_api_data


async def generate_weather_answer(request: WeatherRequest) -> str:
    all_api_data = await fetch_weather_api_data(request)
    current_datetime = datetime.now().strftime("%Y-%m-%d %H")
    combined_api_data = json.dumps(all_api_data, indent=2)
    answer = b.AnswerWeatherQuestion(
        request.question,
        request.location.name,
        current_datetime,
        combined_api_data,
    )
    return answer.answer


async def generate_daily_copenhagen_answer() -> str:
    location = DEFAULT_DAILY_LOCATION
    today = datetime.now().strftime("%Y-%m-%d")
    fixed_plan = {
        "query_type": "forecast",
        "start_date": today,
        "end_date": today,
        "daily": [
            "temperature_2m_min",
            "temperature_2m_max",
        ],
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
            "windspeed_10m",
            "windgusts_10m",
            "weathercode",
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            FORECAST_WEATHER_ENDPOINT,
            params={
                **fixed_plan,
                "latitude": location.latitude,
                "longitude": location.longitude,
            },
        )
        response.raise_for_status()

    all_api_data = [
        {
            "query_type": fixed_plan["query_type"],
            "date_range": f"{fixed_plan['start_date']} to {fixed_plan['end_date']}",
            "data": response.json(),
        }
    ]

    answer = b.AnswerWeatherQuestion(
        (
            "Create a structured morning weather briefing for Copenhagen today. "
            "Use the following section labels exactly once: "
            "Temperatures, Precipitation, Wind, Practical advice, Overall."
        ),
        location.name,
        datetime.now().strftime("%Y-%m-%d %H"),
        json.dumps(all_api_data, indent=2),
    )
    return answer.answer


def build_discord_embed(content: str) -> dict:
    pattern = re.compile(r"(Temperatures|Precipitation|Wind|Practical advice|Overall)\s*[—-]\s*", re.IGNORECASE)
    matches = list(pattern.finditer(content))
    fields: list[dict[str, str | bool]] = []

    if matches:
        for index, match in enumerate(matches):
            label = match.group(1).strip().title()
            section_start = match.end()
            section_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            section_text = content[section_start:section_end].strip().strip(".")
            if section_text:
                fields.append(
                    {
                        "name": label,
                        "value": section_text[:1024],
                        "inline": False,
                    }
                )

    embed: dict = {
        "title": "Morning Briefing - Copenhagen",
        "color": 3447003,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if fields:
        embed["fields"] = fields[:5]
    else:
        embed["description"] = content[:4096]

    return embed


async def send_to_discord(content: str) -> None:
    discord_webhook_url = get_discord_webhook_url()
    if not discord_webhook_url:
        logger.error("Missing DISCORD_WEBHOOK_URL")
        raise HTTPException(status_code=500, detail="DISCORD_WEBHOOK_URL is not configured")

    payload = {
        "content": "Daily weather update for Copenhagen",
        "embeds": [build_discord_embed(content)],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(discord_webhook_url, json=payload)
        if response.status_code >= 400:
            logger.error(
                "Discord webhook returned %s: %s",
                response.status_code,
                response.text,
            )
            raise HTTPException(status_code=502, detail="Failed to deliver message to Discord")


def validate_cron_token(x_cron_token: str | None) -> None:
    cron_shared_secret = get_cron_shared_secret()
    if not cron_shared_secret:
        logger.warning("CRON_SHARED_SECRET is not configured; skipping token validation")
        return

    if x_cron_token != cron_shared_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
