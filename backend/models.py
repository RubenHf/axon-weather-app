
from pydantic import BaseModel

class Location(BaseModel):
    name: str
    latitude: float
    longitude: float

class WeatherRequest(BaseModel):
    question: str
    location: Location

class WeatherResponse(BaseModel):
    answer: str
