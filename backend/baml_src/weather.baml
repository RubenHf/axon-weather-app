// Based from : https://open-meteo.com/en/docs/historical-weather-api


class OpenMeteoHistoricalRequest {
  query_type "archive" | "forecast"
  start_date string
  end_date string
  daily string[]
  hourly string[]
}

function ExtractOpenMeteoHistoricalRequest(question: string, today: string) -> OpenMeteoHistoricalRequest[] {
  client CustomGPT5_4_Mini
  prompt #"
    You extract the parameters needed to call the Open-Meteo Weather API
    to answer a user question. The question can be general and may include relative
    dates or vague locations.

    Rules:
    - Determine the query_type based on the temporal nature of the question:
      * "archive" - for historical data (past dates, year-over-year comparisons, seasonal patterns from history)
      * "forecast" - for future predictions (tomorrow, next week, upcoming days)
    - Use only fields supported by the Weather API.
    - Output 1+ requests with the minimal daily/hourly variables required.
    - Return MULTIPLE requests when the question requires comparing different time periods or needs data from separate date ranges.
    - Dates should be ISO-8601 when possible. Today is {{ today }}.
    
    CRITICAL - Date Range Precision:
    - Be PRECISE with date ranges. Avoid unnecessarily wide ranges.
    - "last year" or "last year's temperature" means the SAME DATE last year (or equivalent period), NOT the entire year.
    - "last month" means the SAME DATE last month (or equivalent period), NOT the entire month.
    - "this time last year" means the same date/week one year ago.
    - Only use wide ranges when explicitly asked (e.g., "throughout last year", "all of January", "the whole month").
    - For comparisons like "temperature last year", use the same date last year or a narrow comparable period (e.g., same week).
    - **MAXIMUM CONTINUOUS DATE RANGE: 1 week (7 days). Never exceed this limit.**
    - For seasonal/historical comparisons ("common for this time of year"), use MULTIPLE SEPARATE requests for the same date/week across different years, NOT one continuous multi-year range.
    
    Examples:
    - "What was the temperature last year?" on 2024-02-04 → Use 2023-02-04 (or 2023-02-01 to 2023-02-07 for weekly comparison)
    - "Temperature throughout last year?" → Use 2023-01-01 to 2023-12-31
    - "Last month's weather" on 2024-02-04 → Use 2024-01-04 (or 2024-01-01 to 2024-01-07)
    - "Weather in January last year" → Use 2023-01-01 to 2023-01-31
    - "Temperature between today and last year" on 2024-02-04 → Return TWO requests: [1) 2024-02-04, 2) 2023-02-04]
    - "Is this weather common for this time of year?" on 2026-02-04 → Return MULTIPLE requests for the same date/week across years:
      [1) 2026-02-04, 2) 2025-02-01 to 2025-02-07, 3) 2024-02-01 to 2024-02-07, 4) 2023-02-01 to 2023-02-07]

    Mappings:
    - Daylight vs shortest day:
      query_type: "archive", daily: ["sunrise","sunset"] for "today" and for winter solstice.
    - January temperature YoY:
      query_type: "archive", daily: ["temperature_2m_mean"] for January this year and last year.
    - Windiness common this time of year:
      query_type: "archive", hourly: ["windspeed_10m","windgusts_10m"] for MULTIPLE SEPARATE requests:
      one for today, and separate requests for the same date/week in previous years (e.g., 3-5 years back).
      DO NOT use a single continuous multi-year range like 2016-2025.
    - Tomorrow cold:
      query_type: "forecast", daily: ["temperature_2m_min","temperature_2m_max"] for "tomorrow".
      Optionally include separate requests for the same date in previous years to define "cold".
    - Temperature comparison between periods:
      Return separate requests for each time period being compared.

    Question:
    {{ question }}

    {{ ctx.output_format }}
  "#
}

test daylight_diff {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "How much longer is daytime (sunrise to sunset) today than the shortest day of the year in my location?"
    today "2026-02-04"
  }
  @@check(two_requests, {{ _.result|length == 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" and _.result[1].query_type == "archive" }})
  @@check(has_sunrise_sunset, {{ "sunrise" in _.result[0].daily and "sunset" in _.result[0].daily }})
  @@assert({{ _.checks.two_requests and _.checks.all_archive and _.checks.has_sunrise_sunset }})
}

test january_temp_yoy {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "Is the temperature this January higher than last year?"
    today "2026-02-04"
  }
  @@check(two_requests, {{ _.result|length == 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" and _.result[1].query_type == "archive" }})
  @@check(has_temperature, {{ _.result[0].daily|length > 0 }})
  @@assert({{ _.checks.two_requests and _.checks.all_archive and _.checks.has_temperature }})
}

test windy_copenhagen {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "It feels windy today in Copenhagen. Is this common for this time of year?"
    today "2026-02-04"
  }
  @@check(multiple_requests, {{ _.result|length >= 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" }})
  @@check(has_wind_data, {{ _.result[0].hourly|length > 0 }})
  @@assert({{ _.checks.multiple_requests and _.checks.all_archive and _.checks.has_wind_data }})
}

test tomorrow_cold {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "Is tomorrow going to be cold?"
    today "2026-02-04"
  }
  @@check(has_requests, {{ _.result|length >= 1 }})
  @@check(is_forecast, {{ _.result[0].query_type == "forecast" }})
  @@check(has_temperature, {{ _.result[0].daily|length > 0 }})
  @@assert({{ _.checks.has_requests and _.checks.is_forecast and _.checks.has_temperature }})
}

test next_week_forecast {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "What will the weather be like next week?"
    today "2026-02-04"
  }
  @@check(has_requests, {{ _.result|length >= 1 }})
  @@check(is_forecast, {{ _.result[0].query_type == "forecast" }})
  @@check(has_fields, {{ _.result[0].daily|length > 0 or _.result[0].hourly|length > 0 }})
  @@assert({{ _.checks.has_requests and _.checks.is_forecast and _.checks.has_fields }})
}

test temperature_comparison_year {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "What is the temperature difference between today and last year?"
    today "2026-02-04"
  }
  @@check(two_requests, {{ _.result|length == 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" and _.result[1].query_type == "archive" }})
  @@check(has_fields, {{ _.result[0].daily|length > 0 or _.result[0].hourly|length > 0 }})
  @@assert({{ _.checks.two_requests and _.checks.all_archive and _.checks.has_fields }})
}

test temperature_between_periods {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "Compare the temperature between today and the same day last year"
    today "2026-02-04"
  }
  @@check(two_requests, {{ _.result|length == 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" and _.result[1].query_type == "archive" }})
  @@check(has_temperature, {{ _.result[0].daily|length > 0 }})
  @@assert({{ _.checks.two_requests and _.checks.all_archive and _.checks.has_temperature }})
}

test windy_common_this_time_of_year {
  functions [ExtractOpenMeteoHistoricalRequest]
  args {
    question "Is this windy weather common for this time of year?"
    today "2026-02-04"
  }
  @@check(multiple_requests, {{ _.result|length >= 2 }})
  @@check(all_archive, {{ _.result[0].query_type == "archive" }})
  @@check(has_wind_data, {{ _.result[0].hourly|length > 0 }})
  @@assert({{ _.checks.multiple_requests and _.checks.all_archive and _.checks.has_wind_data }})
}