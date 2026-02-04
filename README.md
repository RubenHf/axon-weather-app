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

   Add your OpenAI API key to `.env`:
   ```
   OPENAI_API_KEY=your_key_here
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
