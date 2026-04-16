
from datetime import timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from .baml_client.types import DailyBriefAnswer


class Location(BaseModel):
    name: str
    latitude: float
    longitude: float

class WeatherRequest(BaseModel):
    question: str
    location: Location

class WeatherResponse(BaseModel):
    answer: str


class DailyBriefBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    brief: DailyBriefAnswer
    hourly: dict
    tz: timezone | ZoneInfo
