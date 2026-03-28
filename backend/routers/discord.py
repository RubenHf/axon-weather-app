import json

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from ..functions import (
    process_discord_deferred_command,
    process_discord_weather_question,
    format_daily_brief_plain_text,
    generate_daily_copenhagen_answer,
    send_to_discord,
    validate_cron_token,
    validate_discord_signature,
)

from ..models import WeatherRequest
from ..observability import start_observation, with_trace_attributes
from ..settings import DEFAULT_DAILY_LOCATION, DEV_TAG

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/discord",
    tags=["discord"],
    responses={404: {"description": "Not found"}},
)


@router.post("/daily-weather")
async def send_daily_weather_to_discord(
    x_cron_token: str | None = Header(default=None, alias="X-CRON-TOKEN"),
) -> dict:
    with start_observation(
        name="daily-discord-weather",
        as_type="span",
        input={"location": "Copenhagen", "has_cron_token": x_cron_token is not None},
        metadata={"feature": "daily_discord", "endpoint": "/discord/daily-weather"},
    ) as route_observation:
        with with_trace_attributes(
            tags=["daily_discord", DEV_TAG],
            metadata={"location_name": "Copenhagen"},
            trace_name="daily-discord-weather",
        ):
            try:
                validate_cron_token(x_cron_token)
                brief = await generate_daily_copenhagen_answer()
                await send_to_discord(brief)
                payload = {
                    "status": "sent",
                    "brief": brief.model_dump(),
                    "answer": format_daily_brief_plain_text(brief),
                }
                route_observation.update(output=payload, metadata={"http_status_code": 200})
                return payload
            except Exception as exc:
                route_observation.update(
                    output={"status": "error", "error": str(exc)},
                    metadata={"http_status_code": 500},
                )
                raise


@router.post("/interactions")
async def handle_discord_interactions(
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature_ed25519: str | None = Header(default=None, alias="X-Signature-Ed25519"),
    x_signature_timestamp: str | None = Header(default=None, alias="X-Signature-Timestamp"),
) -> dict:
    raw_body = await request.body()
    validate_discord_signature(x_signature_ed25519, x_signature_timestamp, raw_body)

    try:
        interaction = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    interaction_type = interaction.get("type")
    interaction_data = interaction.get("data", {})
    command_name = interaction_data.get("name", "unknown")
    user_id = interaction.get("member", {}).get("user", {}).get("id") or interaction.get("user", {}).get("id")
    username = interaction.get("member", {}).get("user", {}).get("username") or interaction.get("user", {}).get("username")
    guild_id = interaction.get("guild_id")

    with start_observation(
        name="discord-interactions",
        as_type="span",
        input={"username": username, "command_name": command_name, "interaction_type": interaction_type},
        metadata={"feature": "discord_interactions", "endpoint": "/discord/interactions"},
    ) as route_observation:
        with with_trace_attributes(
            tags=["discord_interactions", DEV_TAG],
            metadata={"command_name": command_name, "guild_id": guild_id, "user_id": user_id},
            trace_name="discord-interactions",
        ):
            try:
                if interaction_type == 1:
                    payload = {"type": 1}
                    route_observation.update(output=payload, metadata={"http_status_code": 200})
                    return payload

                if interaction_type != 2:
                    payload = {
                        "type": 4,
                        "data": {"content": "Unsupported interaction type.", "flags": 64},
                    }
                    route_observation.update(
                        output={"status": "unsupported_type", "interaction_type": interaction_type},
                        metadata={"http_status_code": 200},
                    )
                    return payload

                hours_by_command = {"2_hours": 2, "4_hours": 4}
                is_hours_command = command_name in hours_by_command
                is_weather_command = command_name == "weather"
                if not is_hours_command and not is_weather_command:
                    payload = {
                        "type": 4,
                        "data": {
                            "content": "Unknown command. Use `/2_hours`, `/4_hours`, or `/weather`.",
                            "flags": 64,
                        },
                    }
                    route_observation.update(
                        output={"status": "unknown_command", "command_name": command_name},
                        metadata={"http_status_code": 200},
                    )
                    return payload

                interaction_token = interaction.get("token")
                application_id = interaction.get("application_id")
                if not interaction_token or not application_id:
                    payload = {
                        "type": 4,
                        "data": {
                            "content": "Missing interaction token or application id.",
                            "flags": 64,
                        },
                    }
                    route_observation.update(
                        output={"status": "missing_interaction_ids", "command_name": command_name},
                        metadata={"http_status_code": 200},
                    )
                    return payload

                if is_hours_command:
                    window_hours = hours_by_command[command_name]
                    background_tasks.add_task(
                        process_discord_deferred_command,
                        application_id=application_id,
                        interaction_token=interaction_token,
                        window_hours=window_hours,
                        command_name=command_name,
                        guild_id=guild_id,
                        user_id=user_id,
                    )
                    route_observation.update(
                        output={"status": "deferred", "command_name": command_name, "window_hours": window_hours},
                        metadata={"http_status_code": 200},
                    )
                    return {"type": 5, "data": {"flags": 64}}

                options = interaction_data.get("options", [])
                question = next(
                    (
                        option.get("value")
                        for option in options
                        if option.get("name") == "question" and isinstance(option.get("value"), str)
                    ),
                    "",
                ).strip()
                if not question:
                    payload = {
                        "type": 4,
                        "data": {
                            "content": "Please provide a weather question, e.g. `/weather question:Will it rain today?`",
                            "flags": 64,
                        },
                    }
                    route_observation.update(
                        output={"status": "missing_weather_question", "command_name": command_name},
                        metadata={"http_status_code": 200},
                    )
                    return payload

                background_tasks.add_task(
                    process_discord_weather_question,
                    application_id=application_id,
                    interaction_token=interaction_token,
                    weather_request=WeatherRequest(
                        question=question,
                        location=DEFAULT_DAILY_LOCATION,
                    ),
                    command_name=command_name,
                    guild_id=guild_id,
                    user_id=user_id,
                )

                payload = {"type": 5, "data": {"flags": 64}}
                route_observation.update(
                    output={"status": "deferred", "command_name": command_name, "question": question},
                    metadata={"http_status_code": 200},
                )
                return payload
            except Exception as exc:
                logger.error("Failed to process Discord interaction: %s", str(exc))
                payload = {
                    "type": 4,
                    "data": {
                        "content": "Something went wrong while handling this command.",
                        "flags": 64,
                    },
                }
                route_observation.update(
                    output={"status": "error", "error": str(exc), "command_name": command_name},
                    metadata={"http_status_code": 200},
                )
                return payload

