from datetime import datetime, timezone
import json
import logging
import re

import httpx
from .baml_client import b
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
    get_discord_webhook_url,
)

logger = logging.getLogger(__name__)
collector = Collector(name="weather-api")

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
            "gusts": [data["hourly"]["windgusts_10m"][i] for i in indices],
            "rain": [classify_rain(max(data["hourly"]["precipitation"][i: i+3])) for i in indices],
            "weathercode": [WMO.get(data["hourly"]["weathercode"][i], "unknown") for i in indices],
        }
        return reduced
    except Exception as e:
        logger.error("Error reducing hourly data: %s", e)
        return data

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
            {"answer": answer.answer},
        )

        return answer.answer


def build_discord_embed(content: str) -> dict:
    pattern = re.compile(r"(Temperatures|Precipitation|Wind|Air Quality|Practical advice|Overall)\s*[—-]\s*", re.IGNORECASE)
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
    embed = build_discord_embed(content)
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
