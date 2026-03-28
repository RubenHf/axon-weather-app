import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .functions import (
    generate_weather_answer,
    sync_discord_application_commands,
)

from .models import WeatherRequest, WeatherResponse
from .routers import discord
from .observability import shutdown_observability, start_observation, with_trace_attributes
from .settings import ALLOWED_ORIGINS, DEV_TAG, get_docs_url

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    # Syncing the Discord application commands on startup when needed
    try:
        await sync_discord_application_commands()
    except Exception as exc:
        logger.error("Discord command sync failed during startup: %s", str(exc))
    yield
    shutdown_observability()


app = FastAPI(docs_url=get_docs_url(), redoc_url=None, lifespan=app_lifespan)

app.include_router(discord.router)
app.add_middleware(
    CORSMiddleware,  # ty:ignore[invalid-argument-type]
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/weather")
async def get_weather(request: WeatherRequest) -> WeatherResponse:
    with start_observation(
        name="weather-request",
        as_type="span",
        input=request.model_dump(),
        metadata={"feature": "weather_api", "endpoint": "/weather"},
    ) as route_observation:
        with with_trace_attributes(
            tags=["weather_api", DEV_TAG],
            metadata={"location_name": request.location.name},
            trace_name="weather-request",
        ):
            try:
                answer = await generate_weather_answer(request)
                response = WeatherResponse(answer=answer)
                route_observation.update(
                    output={"status": "ok", "answer": answer},
                    metadata={"http_status_code": 200},
                )
                return response
            except Exception as exc:
                logger.error(f"Error processing weather request: {str(exc)}")
                route_observation.update(
                    output={"status": "error", "error": str(exc)},
                    metadata={"http_status_code": 500},
                )
                return WeatherResponse(answer="Sorry, we encountered an error")

