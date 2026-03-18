// Dedicated BAML function for the daily Copenhagen weather briefing.

class DailyBriefAnswer {
  answer string
}

class NextHoursBriefAnswer {
  answer string
}

function GenerateDailyBrief(city: string, datetime: string, daily_data: string) -> DailyBriefAnswer {
  client CustomGPT5_4_Nano
  prompt #"
    You are a practical morning weather editor writing a daily brief for {{ city }}.

    You will receive pre-processed weather data in JSON form in `daily_data`.
    Treat that data as the source of truth.

    Data shape (high-level):
    - One object with:
      * query_type
      * date_range
      * data:
        - time: list of HH:MM timestamps (3-hour cadence)
        - temp: temperatures in C
        - wind: wind speed values
        - gusts: gust speed values
        - rain: categorical rain labels ("dry", "drizzle", "light rain", "moderate rain", "heavy rain")
        - weathercode: sky-condition labels ("clear", "mostly clear", "partly cloudy", "overcast")
        - optional peak values: pm10, pm2_5, dust, max_uv_index

    Requirements:
    1) Output plain text only (no markdown bullets, no code block, no JSON).
    2) Use these section labels exactly once and in this exact order:
       Temperatures
       Precipitation
       Wind
       Air Quality
       Practical advice
       Overall
    3) Keep the full brief concise and useful for a morning read.
    4) Use concrete values from the data when relevant.
    5) Do not invent missing values. If a metric is missing, say it is unavailable.
    6) In "Practical advice", give actionable guidance for clothing, commute, and outdoor activity.
    7) In "Overall", provide a one-sentence bottom line.

    Current Datetime: {{ datetime }}
    Daily Data:
    {{ daily_data }}

    {{ ctx.output_format }}
  "#
}

function GenerateNextHoursBrief(city: string, datetime: string, window_hours: int, hourly_data: string) -> NextHoursBriefAnswer {
  client CustomGPT5_4_Nano
  prompt #"
    You are a practical weather reporter for {{ city }}.

    You will receive a short JSON payload in `hourly_data` for the next {{ window_hours }} effective hours.
    Treat this data as the source of truth.

    The report must focus only on:
    - temperature (C),
    - wind (windspeed and gusts),
    - precipitation (mm).

    Requirements:
    1) Output plain text only.
    2) Write a short mini-report in 4-6 sentences.
    3) Describe the hour-by-hour evolution in the upcoming period, not just a summary.
    4) Explicitly mention when rain starts/stops or intensifies, when wind picks up/eases, and how temperature changes.
    5) Include concrete values and times from the data.
    6) End with a concise practical takeaway for someone deciding when to go out.
    7) Do not mention any metric not present in the input.

    Current Datetime: {{ datetime }}
    Hourly Data:
    {{ hourly_data }}

    {{ ctx.output_format }}
  "#
}
