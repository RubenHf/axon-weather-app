import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from .functions import (
    generate_daily_copenhagen_answer,
    generate_weather_answer,
    send_to_discord,
    validate_cron_token,
)

from .models import WeatherRequest, WeatherResponse
from .observability import shutdown_observability, start_observation, with_trace_attributes
from .settings import ALLOWED_ORIGINS, DEV_TAG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    yield
    shutdown_observability()


app = FastAPI(docs_url="/docs", redoc_url=None, lifespan=app_lifespan)

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


@app.post("/discord/daily-weather")
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
                answer = await generate_daily_copenhagen_answer()
                # await send_to_discord(answer)
                payload = {
                    "status": "sent",
                    "answer": answer,
                }
                route_observation.update(output=payload, metadata={"http_status_code": 200})
                return payload
            except Exception as exc:
                route_observation.update(
                    output={"status": "error", "error": str(exc)},
                    metadata={"http_status_code": 500},
                )
                raise

