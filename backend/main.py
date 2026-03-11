from datetime import datetime
import logging

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from .functions import (
    generate_daily_copenhagen_answer,
    generate_weather_answer,
    send_to_discord,
    validate_cron_token,
)

from .models import WeatherRequest, WeatherResponse
from .settings import ALLOWED_ORIGINS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)

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
    try:
        answer = await generate_weather_answer(request)
        return WeatherResponse(answer=answer)
    except Exception as exc:
        logger.error(f"Error processing weather request: {str(exc)}")
        return WeatherResponse(answer="Sorry, we encountered an error")


@app.post("/discord/daily-weather")
async def send_daily_weather_to_discord(
    x_cron_token: str | None = Header(default=None, alias="X-CRON-TOKEN"),
) -> dict:
    validate_cron_token(x_cron_token)
    answer = await generate_daily_copenhagen_answer()
    await send_to_discord(answer)

    return {
        "status": "sent",
        "location": "Copenhagen",
        "sent_at": datetime.now().isoformat(),
    }
