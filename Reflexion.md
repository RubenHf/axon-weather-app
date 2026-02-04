## Thought process & key decisions

When I need to integrate a new API, I start by testing it in a notebook to get a feel for the parameters and output.

- **Backend**: FastAPI (quick to implement and iterate on).
- **LLM layer**: I used BoundaryML (BAML) because it makes LLM improvement easier:
  - **structured output**: generate validated arguments to call `api.open-meteo.com`
  - **provider-agnostic**: easy to switch models and LLM providers
  - **fast prompt iteration**: generate tests across multiple use cases to improve prompts quickly
- **Frontend**: Next.js (kept intentionally small for this prototype).

For this weather app specifically:

- A user asks general questions, so we need to translate natural language into API parameters. That’s why I added a first step that transforms the user query into arguments for `api.open-meteo.com` using structured output. With BAML, we can test different use cases and iterate on.
- We fetch data from the API and pass it to the “Weather agent” to produce the answer.
- I didn’t implement a full conversational assistant because weather questions are more likely to be one-off rather than an ongoing conversation. That could be a future improvement.

## How happy am I with the outcome?

I’m happy with the results so far. 
It answers the example questions quite accurately. 
We still need proper evaluation/LLMOps to confirm this more rigorously.

## What would I improve first?

1. **LLMOps tracing** (for example Langfuse) to track and debug all LLM outputs (argument extraction and final answer).
2. **Evaluations** to measure output quality.
3. **UX**: make the frontend and the LLM answers more user-friendly.

Note: I didn’t put evaluations first because we already have tests covering multiple use cases, but those tests should be complemented with proper evalaluations.

