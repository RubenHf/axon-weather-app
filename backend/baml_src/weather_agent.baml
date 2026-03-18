// Weather Agent - Answers user questions based on weather API data

class WeatherAnswer {
  answer string
//   confidence string // "high", "medium", "low"
//   key_facts string[] // Important facts extracted from the data
}

function AnswerWeatherQuestion(question: string, city: string, datetime: string, api_response: string) -> WeatherAnswer {
  client CustomGPT5_4_Nano
  prompt #"
    You are a weather expert analyzing API data to answer user questions about weather conditions in the city {{ city }}.

    Your task is to analyze the Open-Meteo API response data and provide a clear, natural answer to the user's question.

    API Response Structure:
    The api_response may contain one or more API responses from Open-Meteo API. When multiple responses are provided,
    they represent different time periods that need to be compared or analyzed together.
    
    Each response may include:
    - query_type: "archive" (historical) or "forecast" (future predictions)
    - date_range: The date range this response covers
    - data: The actual API response containing:
      * latitude/longitude: Location coordinates
      * generationtime_ms: API processing time
      * utc_offset_seconds: Timezone offset
      * timezone: Timezone name
      * elevation: Location elevation in meters
      * daily: Daily weather data (temperature, precipitation, wind, sunrise/sunset, etc.)
      * hourly: Hourly weather data (temperature, humidity, wind speed, etc.)
      * daily_units/hourly_units: Units for the measurements

    Instructions:
    1. If multiple API responses are provided, compare and analyze them together to answer the question
    2. Extract key facts and measurements from the data
    3. When comparing periods (e.g., today vs last year), clearly show the difference or trend
    4. Provide a clear, conversational answer in the context of the city {{ city }}
    5. Include specific numbers and units when relevant
    {# 4. List the most important facts that support your answer #}

    Question: {{ question }}
    Current Datetime: {{ datetime }}
    API Response(s):
    {{ api_response }}

    {{ ctx.output_format }}
  "#
}