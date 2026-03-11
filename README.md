## Prerequisites

- [uv](https://docs.astral.sh/uv/) - Python package manager (for backend)
- [Bun](https://bun.sh/) - JavaScript runtime (for frontend)

## Setup

1. **Install BAML**

   Follow the official guide: https://docs.boundaryml.com/

2. **Create virtual environment**

   ```bash
   uv venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   uv sync
   ```

4. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Add your API keys and integration settings to `.env`:
   ```
   OPENAI_API_KEY=your_key_here
   DISCORD_WEBHOOK_URL=your_discord_webhook_url
   CRON_SHARED_SECRET=your_random_shared_secret
   ```

## Running

```bash
# Run both backend and frontend
make dev

# Run backend only
make dev-backend

# Run frontend only
make dev-frontend
```

## Discord Daily Weather Route

Trigger a daily Copenhagen weather message to Discord:

```bash
curl -X POST http://127.0.0.1:8000/discord/daily-weather \
  -H "X-CRON-TOKEN: your_random_shared_secret"
```

- `DISCORD_WEBHOOK_URL` is required to deliver messages.
- If `CRON_SHARED_SECRET` is set, requests must include `X-CRON-TOKEN`.

## Docker

- Have Docker installed and launched
```bash
docker build -t weather-app .
docker run -p 8000:8000 weather-app
```