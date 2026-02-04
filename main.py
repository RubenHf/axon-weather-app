

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import httpx
import json
from baml_client import b
from dotenv import load_dotenv
from fastapi import HTTPException
from backend.models import WeatherRequest
from backend.models import WeatherResponse

load_dotenv()

app = FastAPI()

# Add CORS middleware to allow requests from frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/weather")
async def get_weather(request: WeatherRequest) -> WeatherResponse:
    today = datetime.now().strftime("%Y-%m-%d")

    weather_api_plans = b.ExtractOpenMeteoHistoricalRequest(request.question, today)

    # Validate date ranges are not too wide (max 1 year continuous)
    MAX_DAYS_RANGE = 366  # Allow 1 year + 1 day for leap years
    
    for plan in weather_api_plans:
        try:
            start = datetime.strptime(plan.start_date, "%Y-%m-%d")
            end = datetime.strptime(plan.end_date, "%Y-%m-%d")
            days_diff = (end - start).days
            
            if days_diff > MAX_DAYS_RANGE:
                raise HTTPException(
                    status_code=400,
                    detail=f"Date range too wide: {plan.start_date} to {plan.end_date} ({days_diff} days). "
                           f"Maximum allowed is {MAX_DAYS_RANGE} days per request. "
                           f"For historical comparisons, please use multiple separate requests for the same date across different years."
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")

    all_api_data = []
    
    async with httpx.AsyncClient() as client:
        for plan in weather_api_plans:
            api_params = plan.model_dump()
            
            # Determine API endpoint based on query_type
            query_type = api_params.pop("query_type")
            if query_type == "archive":
                api_endpoint = "https://archive-api.open-meteo.com/v1/archive"
            elif query_type == "forecast":
                api_endpoint = "https://api.open-meteo.com/v1/forecast"
            else:
                raise HTTPException(status_code=400, detail="Invalid query type")

            response = await client.get(
                api_endpoint,
                params={
                    **api_params,
                    "latitude": request.location.latitude,
                    "longitude": request.location.longitude,
                }
            )

            api_data = response.json()
            all_api_data.append({
                "query_type": query_type,
                "date_range": f"{api_params.get('start_date')} to {api_params.get('end_date')}",
                "data": api_data
            })

    current_datetime = datetime.now().strftime("%Y-%m-%d %H")

    # Weather agent analyzes the data and answers the question
    combined_api_data = json.dumps(all_api_data, indent=2)
    answer = b.AnswerWeatherQuestion(request.question, request.location.name, current_datetime, combined_api_data)   

    return WeatherResponse(answer=answer.answer)
