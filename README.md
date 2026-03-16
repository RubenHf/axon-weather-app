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
   DISCORD_PUBLIC_KEY=your_discord_app_public_key
   DISCORD_BOT_TOKEN=your_discord_bot_token
   DISCORD_APPLICATION_ID=your_discord_application_id
   DISCORD_GUILD_ID=your_discord_server_id
   CRON_SHARED_SECRET=your_random_shared_secret
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

   For US cloud, set `LANGFUSE_BASE_URL=https://us.cloud.langfuse.com`.

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

## Discord Interactions (Discord -> Backend)

Use this to let Discord invoke your backend via slash commands.

1. Expose your backend publicly over HTTPS (for example with Fly, Railway, or ngrok during development).
2. In Discord Developer Portal -> your application -> General Information, copy the **Public Key** into:
   - `DISCORD_PUBLIC_KEY` in `.env`.
3. In Discord Developer Portal -> your application -> **Interactions Endpoint URL**, set:
   - `https://<your-domain>/discord/interactions`
4. Configure your bot credentials so commands can be synced on backend startup:
   - `DISCORD_BOT_TOKEN`
   - `DISCORD_APPLICATION_ID`
   - `DISCORD_GUILD_ID`
5. Start the backend. On startup, it bulk-overwrites Discord application commands and keeps only:
   - `/2_hours`
   - `/4_hours`

Implemented interaction behavior:
- `type=1` Ping returns `{"type":1}` for Discord validation.
- `/2_hours` and `/4_hours` return deferred ack (`{"type":5}`) immediately.
- The backend then runs weather + LLM processing in a background task.
- Final response is posted as an ephemeral follow-up message (only visible to the command user).

## Docker

- Have Docker installed and launched
```bash
docker build -t weather-app .
docker run -p 8000:8000 weather-app
```