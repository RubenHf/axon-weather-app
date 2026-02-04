from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import httpx
import json
import logging
from baml_client import b
from dotenv import load_dotenv
from fastapi import HTTPException
from models import WeatherRequest
from models import WeatherResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,  # ty:ignore[invalid-argument-type]
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
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Extracting API parameters for question: {request.question}")
        weather_api_plans = b.ExtractOpenMeteoHistoricalRequest(request.question, today)

        # In case of too much context for the agent to handle
        MAX_DAYS_RANGE = 16
        
        for plan in weather_api_plans:
            try:
                start = datetime.strptime(plan.start_date, "%Y-%m-%d")
                end = datetime.strptime(plan.end_date, "%Y-%m-%d")
                days_diff = (end - start).days

                logger.debug(f"Validating date range: {plan.start_date} to {plan.end_date} ({days_diff} days)")

                if days_diff > MAX_DAYS_RANGE:
                    logger.warning(f"Date range too wide: {days_diff} days for plan {plan.start_date} to {plan.end_date}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Date range too wide: {plan.start_date} to {plan.end_date} ({days_diff} days). "
                            f"Maximum allowed is {MAX_DAYS_RANGE} days per request. "
                            f"For historical comparisons, please use multiple separate requests for the same date across different years."
                    )
            except ValueError as e:
                logger.error(f"Invalid date format in plan: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")

        all_api_data = []
        logger.info(f"Making {len(weather_api_plans)} API calls to Open-Meteo API")

        async with httpx.AsyncClient() as client:
            for plan in weather_api_plans:
                api_params = plan.model_dump()

                # API endpoint based on query_type
                query_type = api_params.pop("query_type")
                if query_type == "archive":
                    api_endpoint = "https://archive-api.open-meteo.com/v1/archive"
                elif query_type == "forecast":
                    api_endpoint = "https://api.open-meteo.com/v1/forecast"
                else:
                    logger.error(f"Invalid query type: {query_type}")
                    raise HTTPException(status_code=400, detail="Invalid query type")

                logger.info(f"Calling {query_type} API: {api_endpoint} for dates {api_params.get('start_date')} to {api_params.get('end_date')}")
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

    except Exception as e:
        logger.error(f"Error processing weather request: {str(e)}")
        return WeatherResponse(answer="Sorry, we encountered an error")
