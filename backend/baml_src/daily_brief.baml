// Dedicated BAML function for the daily Copenhagen weather briefing.

class DailyBriefAnswer {
  answer string
}

function GenerateDailyBrief(city: string, datetime: string, daily_data: string) -> DailyBriefAnswer {
  client CustomGPT5Mini
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
