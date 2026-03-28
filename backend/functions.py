from datetime import datetime, timezone
import json
import logging
from zoneinfo import ZoneInfo

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from .baml_client import b
from .baml_client.types import DailyBriefAnswer
from baml_py import Collector
from fastapi import HTTPException

from .models import WeatherRequest
from .observability import start_observation
from .settings import (
    ARCHIVE_WEATHER_ENDPOINT,
    DEFAULT_DAILY_LOCATION,
    FORECAST_WEATHER_ENDPOINT,
    AIR_QUALITY_ENDPOINT,
    MAX_DAYS_RANGE,
    get_cron_shared_secret,
    get_discord_application_id,
    get_discord_bot_token,
    get_discord_guild_id,
    get_discord_public_key,
    get_discord_webhook_url,
)

logger = logging.getLogger(__name__)
collector = Collector(name="weather-api")


def _safe_timezone(timezone_name: str | None) -> timezone | ZoneInfo:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        logger.warning("Invalid timezone from forecast response: %s", timezone_name)
        return timezone.utc

def build_weather_endpoint(query_type: str) -> str:
    if query_type == "archive":
        return ARCHIVE_WEATHER_ENDPOINT
    if query_type == "forecast":
        return FORECAST_WEATHER_ENDPOINT
    if query_type == "air_quality":
        return AIR_QUALITY_ENDPOINT
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


def extract_input_and_model(result):
    body = result.http_request.body.json()  # There is a need to convert HTTPBody → dict

    model_name = body["model"]
    input_text = body["input"][0]["content"][0]["text"]

    return input_text, model_name


def update_observation_from_last_call(observation, output):
    # To update some information from BAML like the model name and tokens usage.
    last = collector.last
    if last is None or not last.calls:
        logger.warning("Collector has no calls; updating observation with output only")
        observation.update(output=output)
        return

    last_call = last.calls[-1]
    input_text, model_name = extract_input_and_model(last_call)
    input_tokens = last_call.usage.input_tokens or 0
    output_tokens = last_call.usage.output_tokens or 0
    total_tokens = input_tokens + output_tokens

    observation.update(
        input=input_text,
        model=model_name,
        usage={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
        output=output,
    )

async def fetch_weather_api_data(request: WeatherRequest) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info("Extracting API parameters for question: %s", request.question)
    with start_observation(
        name="extract-weather-plan",
        as_type="generation",
        metadata={"baml_function": "ExtractOpenMeteoHistoricalRequest"},
        model="",
    ) as extraction_observation:
        weather_api_plans = b.ExtractOpenMeteoHistoricalRequest(request.question, today, baml_options={"collector": collector})
        weather_api_plans_payload = [plan.model_dump() for plan in weather_api_plans]
        update_observation_from_last_call(
            extraction_observation,
            weather_api_plans_payload,
        )

    with start_observation(
        name="validate-weather-plan-dates",
        as_type="span",
        input={"weather_api_plans": weather_api_plans_payload},
    ) as validation_observation:
        validate_weather_api_plan_dates(weather_api_plans)
        validation_observation.update(output={"valid_plan_count": len(weather_api_plans)})

    all_api_data: list[dict] = []
    logger.info("Making %s API calls to Open-Meteo API", len(weather_api_plans))

    async with httpx.AsyncClient() as client:
        for plan in weather_api_plans:
            api_params = plan.model_dump()
            query_type = api_params.pop("query_type")
            api_endpoint = build_weather_endpoint(query_type)
            request_params = {
                **api_params,
                "latitude": request.location.latitude,
                "longitude": request.location.longitude,
            }
            logger.info(
                "Calling %s API: %s for dates %s to %s",
                query_type,
                api_endpoint,
                api_params.get("start_date"),
                api_params.get("end_date"),
            )

            with start_observation(
                name=f"open-meteo-{query_type}",
                as_type="span",
                input={
                    "endpoint": api_endpoint,
                    "query_type": query_type,
                    "params": request_params,
                },
            ) as weather_api_observation:
                response = await client.get(api_endpoint, params=request_params)
                response.raise_for_status()
                response_data = response.json()
                weather_api_observation.update(
                    output={
                        "status_code": response.status_code,
                        "query_type": query_type,
                        "response": response_data,
                    }
                )

            all_api_data.append(
                {
                    "query_type": query_type,
                    "date_range": f"{api_params.get('start_date')} to {api_params.get('end_date')}",
                    "data": response_data,
                }
            )

    return all_api_data


async def generate_weather_answer(request: WeatherRequest) -> str:
    all_api_data = await fetch_weather_api_data(request)
    current_datetime = datetime.now().strftime("%Y-%m-%d %H")
    combined_api_data = json.dumps(all_api_data, indent=2)
    with start_observation(
        name="answer-weather-question",
        as_type="generation",
        metadata={"baml_function": "AnswerWeatherQuestion"},
        model="baml",
    ) as answer_observation:
        answer = b.AnswerWeatherQuestion(
            request.question,
            request.location.name,
            current_datetime,
            combined_api_data,
            baml_options={"collector": collector},
        )
        update_observation_from_last_call(
            answer_observation,
            {"answer": answer.answer},
        )
        return answer.answer

def classify_wind_direction(degrees: float, sectors: int = 8) -> str | None:
    """
    Convert wind direction in degrees to compass direction (8/16-point).
    """
    if degrees is None:
        return None

    if sectors == 16:
        directions = [
            "N", "NNE", "NE", "ENE",
            "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW",
            "W", "WNW", "NW", "NNW"
        ]
        # Each sector is 22.5°
        index = int((degrees + 11.25) % 360 / 22.5)
    else:
        directions = [
            "N", "NE", "E", "SE",
            "S", "SW", "W", "NW"
        ]

        # Each sector is 45°
        index = int((degrees + 22.5) % 360 / 45)
    return directions[index]

def reduce_hourly_data(data: dict) -> dict:
    try: 
        indices = range(0, 24, 3)
        WMO = {
            0: "clear",
            1: "mostly clear",
            2: "partly cloudy",
            3: "overcast",
            45: "fog",
            48: "rime fog",
            51: "light drizzle",
            53: "moderate drizzle",
            55: "dense drizzle",
            56: "light freezing drizzle",
            57: "dense freezing drizzle",
            61: "light rain",
            63: "moderate rain",
            65: "heavy rain",
            66: "light freezing rain",
            67: "heavy freezing rain",
            71: "light snow",
            73: "moderate snow",
            75: "heavy snow",
            77: "snow grains",
            80: "light rain showers",
            81: "moderate rain showers",
            82: "violent rain showers",
            85: "light snow showers",
            86: "heavy snow showers",
            95: "thunderstorm",
            96: "thunderstorm with light hail",
            99: "thunderstorm with heavy hail",
        }

        def classify_rain(mm):
            if mm == 0:
                return "dry"
            if mm < 0.2:
                return "drizzle"
            if mm < 2:
                return "light rain"
            if mm < 5:
                return "moderate rain"
            return "heavy rain"

        reduced = {
            "time": [data["hourly"]["time"][i].split("T")[1] for i in indices],
            "temp": [data["hourly"]["temperature_2m"][i] for i in indices],
            "wind": [data["hourly"]["windspeed_10m"][i] for i in indices],
            "wind_direction": [classify_wind_direction(sum(data["hourly"]["wind_direction_10m"][i: i+3]) / len(data["hourly"]["wind_direction_10m"][i: i+3])) for i in indices],
            "gusts": [data["hourly"]["windgusts_10m"][i] for i in indices],
            "rain": [classify_rain(max(data["hourly"]["precipitation"][i: i+3])) for i in indices],
            "weathercode": [WMO.get(data["hourly"]["weathercode"][i], "unknown") for i in indices],
        }
        return reduced
    except Exception as e:
        logger.error("Error reducing hourly data: %s", e)
        return data

async def generate_daily_copenhagen_answer() -> DailyBriefAnswer:
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
            "wind_direction_10m",
        ],
    }
    air_quality_plan = {
        "hourly": [
            "pm10",
            "pm2_5",
            "dust",
            "uv_index",
        ],
        "forecast_days": 1,
    }

    with start_observation(
        name="daily-weather-fetch",
        as_type="span",
        input={"location": location.model_dump(), "date": today},
    ) as daily_fetch_observation:
        async with httpx.AsyncClient() as client:
            forecast_params = {
                **fixed_plan,
                "latitude": location.latitude,
                "longitude": location.longitude,
            }
            with start_observation(
                name="open-meteo-forecast",
                as_type="span",
                input={
                    "endpoint": FORECAST_WEATHER_ENDPOINT,
                    "query_type": "forecast",
                    "params": forecast_params,
                },
            ) as forecast_observation:
                response = await client.get(
                    FORECAST_WEATHER_ENDPOINT,
                    params=forecast_params,
                )
                response.raise_for_status()
                forecast_data = response.json()
                forecast_observation.update(
                    output={"status_code": response.status_code, "response": forecast_data}
                )

            air_quality_params = {
                **air_quality_plan,
                "latitude": location.latitude,
                "longitude": location.longitude,
            }
            with start_observation(
                name="open-meteo-air-quality",
                as_type="span",
                input={
                    "endpoint": AIR_QUALITY_ENDPOINT,
                    "query_type": "air_quality",
                    "params": air_quality_params,
                },
            ) as air_quality_observation:
                air_quality_response = await client.get(
                    AIR_QUALITY_ENDPOINT,
                    params=air_quality_params,
                )
                air_quality_response.raise_for_status()
                air_quality_data = air_quality_response.json()
                air_quality_observation.update(
                    output={
                        "status_code": air_quality_response.status_code,
                        "response": air_quality_data,
                    }
                )

        hourly_air_quality = air_quality_data.get("hourly", {})
        pm10_values = [value for value in hourly_air_quality.get("pm10", []) if value is not None]
        pm2_5_values = [value for value in hourly_air_quality.get("pm2_5", []) if value is not None]
        dust_values = [value for value in hourly_air_quality.get("dust", []) if value is not None]
        uv_index_values = [value for value in hourly_air_quality.get("uv_index", []) if value is not None]

        max_pm10 = max(pm10_values) if pm10_values else None
        max_pm2_5 = max(pm2_5_values) if pm2_5_values else None
        max_dust = max(dust_values) if dust_values else None
        max_uv_index = max(uv_index_values) if uv_index_values else None

        weather_data = reduce_hourly_data(forecast_data)
        if max_pm10 is not None:
            weather_data["pm10"] = max_pm10
        if max_pm2_5 is not None:
            weather_data["pm2_5"] = max_pm2_5
        if max_dust is not None and max_dust > 0:
            weather_data["dust"] = max_dust
        if max_uv_index is not None:
            weather_data["max_uv_index"] = max_uv_index
        daily_fetch_observation.update(
            output={
                "weather_data": weather_data,
                "max_pm10": max_pm10,
                "max_pm2_5": max_pm2_5,
                "max_dust": max_dust,
                "max_uv_index": max_uv_index,
            }
        )

    all_api_data = [
        {
            "query_type": fixed_plan["query_type"],
            "date_range": f"{fixed_plan['start_date']} to {fixed_plan['end_date']}",
            "data": weather_data,
        }
    ]

    current_datetime = datetime.now().strftime("%Y-%m-%d %H")
    daily_api_data = json.dumps(all_api_data, indent=2)
    with start_observation(
        name="daily-answer",
        as_type="generation",
        metadata={"baml_function": "GenerateDailyBrief"},
        # model="baml",
    ) as daily_answer_observation:
        answer = b.GenerateDailyBrief(
            location.name,
            current_datetime,
            daily_api_data,
            baml_options={"collector": collector},
        )
        update_observation_from_last_call(
            daily_answer_observation,
            {"brief": answer.model_dump()},
        )

        return answer


async def fetch_next_hours_weather_data(window_hours: int) -> dict:
    location = DEFAULT_DAILY_LOCATION
    if window_hours not in (2, 4):
        raise HTTPException(status_code=400, detail="window_hours must be 2 or 4")
    effective_hours = window_hours + 1

    forecast_params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "hourly": [
            "temperature_2m",
            "precipitation",
            "windspeed_10m",
            "windgusts_10m",
            "wind_direction_10m",
        ],
        "forecast_days": 2,
        "timezone": "auto",
    }

    with start_observation(
        name="next-hours-weather-fetch",
        as_type="span",
        input={
            "location": location.model_dump(),
            "window_hours": window_hours,
            "effective_hours": effective_hours,
        },
    ) as fetch_observation:
        async with httpx.AsyncClient() as client:
            response = await client.get(FORECAST_WEATHER_ENDPOINT, params=forecast_params)
            response.raise_for_status()
            forecast_data = response.json()

        timezone_name = forecast_data.get("timezone")
        tz = _safe_timezone(timezone_name)
        now_local = datetime.now(tz=tz)
        hour_floor = now_local.replace(minute=0, second=0, microsecond=0)

        hourly = forecast_data.get("hourly", {})
        times = hourly.get("time", [])
        temperatures = hourly.get("temperature_2m", [])
        precipitation = hourly.get("precipitation", [])
        windspeed = hourly.get("windspeed_10m", [])
        windgusts = hourly.get("windgusts_10m", [])
        wind_direction = hourly.get("wind_direction_10m", [])
        rows: list[dict] = []
        for index, time_value in enumerate(times):
            try:
                dt = datetime.fromisoformat(time_value).replace(tzinfo=tz)
            except ValueError:
                continue
            if dt < hour_floor:
                continue
            rows.append(
                {
                    "time": dt.strftime("%Y-%m-%d %H:%M"),
                    "temperature_2m": temperatures[index] if index < len(temperatures) else None,
                    "precipitation": precipitation[index] if index < len(precipitation) else None,
                    "windspeed_10m": windspeed[index] if index < len(windspeed) else None,
                    "windgusts_10m": windgusts[index] if index < len(windgusts) else None,
                    "wind_direction_10m": classify_wind_direction(wind_direction[index]) if index < len(wind_direction) else None,
                }
            )
            if len(rows) >= effective_hours:
                break

        if not rows:
            logger.error("No forecast rows found for next %s hours", window_hours)
            raise HTTPException(status_code=502, detail="No forecast data available for requested window")

        result = {
            "city": location.name,
            "timezone": timezone_name,
            "window_hours": window_hours,
            "effective_hours": effective_hours,
            "generated_at": now_local.strftime("%Y-%m-%d %H:%M"),
            "hours": rows,
        }
        fetch_observation.update(
            output={
                "window_hours": window_hours,
                "effective_hours": effective_hours,
                "rows_count": len(rows),
                "timezone": timezone_name,
                "weather_data": result,
            }
        )
        return result


async def generate_next_hours_answer(window_hours: int) -> str:
    weather_data = await fetch_next_hours_weather_data(window_hours)
    weather_data_payload = json.dumps(weather_data, indent=2)
    current_datetime = datetime.now().strftime("%Y-%m-%d %H")

    with start_observation(
        name="next-hours-answer",
        as_type="generation",
        metadata={"baml_function": "GenerateNextHoursBrief"},
    ) as answer_observation:
        answer = b.GenerateNextHoursBrief(
            weather_data["city"],
            current_datetime,
            weather_data["effective_hours"],
            weather_data_payload,
            baml_options={"collector": collector},
        )
        update_observation_from_last_call(
            answer_observation,
            {"answer": answer.answer, "window_hours": window_hours},
        )
        return answer.answer


async def sync_discord_application_commands() -> None:
    discord_bot_token = get_discord_bot_token()
    discord_application_id = get_discord_application_id()
    discord_guild_id = get_discord_guild_id()
    if not discord_bot_token or not discord_application_id or not discord_guild_id:
        logger.info(
            "Skipping Discord command sync (missing DISCORD_BOT_TOKEN or DISCORD_APPLICATION_ID or DISCORD_GUILD_ID)"
        )
        return

    commands_url = f"https://discord.com/api/v10/applications/{discord_application_id}/guilds/{discord_guild_id}/commands"
    # Setting up the commands for discord users
    command_payload = [
        {
            "name": "2_hours",
            "description": "Get weather for the next 2 hours in Copenhagen",
            "type": 1,
        },
        {
            "name": "4_hours",
            "description": "Get weather for the next 4 hours in Copenhagen",
            "type": 1,
        },
        {
            "name": "weather",
            "description": "Get weather for a specific question",
            "type": 1,
            "options": [
                {
                    "type": 3,
                    "name": "question",
                    "description": "Your weather question",
                    "required": True,
                    "max_length": 400,
                }
            ],
        },
    ]
    headers = {
        "Authorization": f"Bot {discord_bot_token}",
        "Content-Type": "application/json",
    }

    with start_observation(
        name="discord-command-sync",
        as_type="span",
        input={"commands": [command["name"] for command in command_payload]},
        metadata={"discord_application_id": discord_application_id},
    ) as command_sync_observation:
        async with httpx.AsyncClient() as client:
            response = await client.put(commands_url, headers=headers, json=command_payload)
            if response.status_code >= 400:
                logger.error(
                    "Discord command sync failed with %s: %s",
                    response.status_code,
                    response.text,
                )
                command_sync_observation.update(
                    output={
                        "status": "error",
                        "status_code": response.status_code,
                        "response": response.text,
                    }
                )
                raise HTTPException(
                    status_code=502,
                    detail="Failed to sync Discord application commands",
                )

        logger.info("Discord commands synced: /2_hours, /4_hours, /weather")
        command_sync_observation.update(
            output={"status": "ok", "status_code": response.status_code}
        )


async def post_discord_interaction_followup(
    application_id: str,
    interaction_token: str,
    content: str,
) -> None:
    followup_url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
    payload = {
        "content": content if len(content) <= 2000 else f"{content[:1997]}...",
        "flags": 64,
    }

    with start_observation(
        name="discord-followup-post",
        as_type="span",
        input={"has_application_id": bool(application_id), "payload_flags": payload["flags"]},
    ) as followup_observation:
        async with httpx.AsyncClient() as client:
            response = await client.post(followup_url, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Discord follow-up returned %s: %s",
                    response.status_code,
                    response.text,
                )
                followup_observation.update(
                    output={
                        "status": "error",
                        "status_code": response.status_code,
                        "response": response.text,
                    }
                )
                raise HTTPException(status_code=502, detail="Failed to deliver deferred Discord response")
            followup_observation.update(
                output={"status": "ok", "status_code": response.status_code}
            )


async def process_discord_deferred_command(
    application_id: str,
    interaction_token: str,
    window_hours: int,
    command_name: str,
    guild_id: str | None,
    user_id: str | None,
) -> None:
    with start_observation(
        name="discord-deferred-command",
        as_type="span",
        input={"command_name": command_name, "window_hours": window_hours},
        metadata={"guild_id": guild_id, "user_id": user_id},
    ) as deferred_observation:
        try:
            answer = await generate_next_hours_answer(window_hours)
            await post_discord_interaction_followup(
                application_id=application_id,
                interaction_token=interaction_token,
                content=answer,
            )
            deferred_observation.update(
                output={"status": "ok", "command_name": command_name, "window_hours": window_hours}
            )
        except Exception as exc:
            logger.error("Failed deferred Discord command %s: %s", command_name, str(exc))
            try:
                await post_discord_interaction_followup(
                    application_id=application_id,
                    interaction_token=interaction_token,
                    content="Could not generate your weather update right now. Please try again.",
                )
            except Exception as followup_exc:
                logger.error("Failed sending deferred Discord error follow-up: %s", str(followup_exc))
            deferred_observation.update(
                output={
                    "status": "error",
                    "command_name": command_name,
                    "window_hours": window_hours,
                    "error": str(exc),
                }
            )


async def process_discord_weather_question(
    application_id: str,
    interaction_token: str,
    weather_request: WeatherRequest,
    command_name: str,
    guild_id: str | None,
    user_id: str | None,
) -> None:
    with start_observation(
        name="discord-weather-command",
        as_type="span",
        input={"command_name": command_name, "question": weather_request.question},
        metadata={"guild_id": guild_id, "user_id": user_id},
    ) as weather_observation:
        try:
            answer = await generate_weather_answer(weather_request)
            await post_discord_interaction_followup(
                application_id=application_id,
                interaction_token=interaction_token,
                content=answer,
            )
            weather_observation.update(
                output={"status": "ok", "command_name": command_name}
            )
        except Exception as exc:
            logger.error("Failed Discord weather command %s: %s", command_name, str(exc))
            try:
                await post_discord_interaction_followup(
                    application_id=application_id,
                    interaction_token=interaction_token,
                    content="Could not generate your weather answer right now. Please try again.",
                )
            except Exception as followup_exc:
                logger.error("Failed sending Discord weather error follow-up: %s", str(followup_exc))
            weather_observation.update(
                output={
                    "status": "error",
                    "command_name": command_name,
                    "question": weather_request.question,
                    "error": str(exc),
                }
            )


DISCORD_EMBED_FIELD_VALUE_MAX = 1024
DISCORD_EMBED_DESCRIPTION_MAX = 4096
DISCORD_EMBED_FIELDS_MAX = 25

DAILY_BRIEF_EMBED_SECTIONS: list[tuple[str, str]] = [
    ("Temperatures", "temperatures"),
    ("Precipitation", "precipitation"),
    ("Wind", "wind"),
    ("Air Quality", "air_quality"),
    ("Practical advice", "practical_advice"),
    ("Overall", "overall"),
]


def format_daily_brief_plain_text(brief: DailyBriefAnswer) -> str:
    """Human-readable brief for API responses and embed fallbacks."""
    parts: list[str] = []
    for label, attr in DAILY_BRIEF_EMBED_SECTIONS:
        text = getattr(brief, attr, "").strip()
        if text:
            parts.append(f"{label}\n{text}")
    return "\n\n".join(parts)


def _truncate_discord_field_value(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= DISCORD_EMBED_FIELD_VALUE_MAX:
        return stripped
    return stripped[: DISCORD_EMBED_FIELD_VALUE_MAX - 1] + "…"


def build_discord_embed(brief: DailyBriefAnswer) -> dict:
    embed: dict = {
        "title": "Morning Briefing - Copenhagen",
        "color": 3447003,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    fields: list[dict[str, str | bool]] = []
    for label, attr in DAILY_BRIEF_EMBED_SECTIONS:
        text = getattr(brief, attr, "").strip()
        if text:
            fields.append(
                {
                    "name": label,
                    "value": _truncate_discord_field_value(text),
                    "inline": False,
                }
            )

    if fields:
        embed["fields"] = fields[:DISCORD_EMBED_FIELDS_MAX]
    else:
        plain = format_daily_brief_plain_text(brief)
        description = (
            plain if plain.strip() else "The daily brief could not be generated with valid sections."
        )
        embed["description"] = description[:DISCORD_EMBED_DESCRIPTION_MAX]

    return embed


async def send_to_discord(brief: DailyBriefAnswer) -> None:
    discord_webhook_url = get_discord_webhook_url()
    embed = build_discord_embed(brief)
    with start_observation(
        name="discord-webhook-post",
        as_type="span",
        input={
            "has_discord_webhook_url": bool(discord_webhook_url),
            "content": "Daily weather update for Copenhagen",
            "embed": embed,
        },
    ) as discord_observation:
        if not discord_webhook_url:
            logger.error("Missing DISCORD_WEBHOOK_URL")
            discord_observation.update(
                output={"status": "error", "reason": "DISCORD_WEBHOOK_URL is not configured"}
            )
            raise HTTPException(status_code=500, detail="DISCORD_WEBHOOK_URL is not configured")

        payload = {
            "content": "Daily weather update for Copenhagen",
            "embeds": [embed],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(discord_webhook_url, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "Discord webhook returned %s: %s",
                    response.status_code,
                    response.text,
                )
                discord_observation.update(
                    output={
                        "status": "error",
                        "status_code": response.status_code,
                        "response": response.text,
                    }
                )
                raise HTTPException(status_code=502, detail="Failed to deliver message to Discord")
            discord_observation.update(
                output={"status": "ok", "status_code": response.status_code}
            )


def validate_cron_token(x_cron_token: str | None) -> None:
    cron_shared_secret = get_cron_shared_secret()
    if not cron_shared_secret:
        logger.warning("CRON_SHARED_SECRET is not configured; skipping token validation")
        return

    if x_cron_token != cron_shared_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


def validate_discord_signature(
    x_signature_ed25519: str | None,
    x_signature_timestamp: str | None,
    raw_body: bytes,
) -> None:
    discord_public_key = get_discord_public_key()
    if not discord_public_key:
        logger.error("Missing DISCORD_PUBLIC_KEY")
        raise HTTPException(status_code=500, detail="DISCORD_PUBLIC_KEY is not configured")

    if not x_signature_ed25519 or not x_signature_timestamp:
        raise HTTPException(status_code=401, detail="Missing Discord signature headers")

    try:
        verify_key = VerifyKey(bytes.fromhex(discord_public_key))
        signature = bytes.fromhex(x_signature_ed25519)
        signed_message = x_signature_timestamp.encode("utf-8") + raw_body
        verify_key.verify(signed_message, signature)
    except (ValueError, BadSignatureError) as exc:
        logger.warning("Invalid Discord interaction signature: %s", str(exc))
        raise HTTPException(status_code=401, detail="Invalid request signature")
