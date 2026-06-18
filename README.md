# Boynton Bot

Personal AI assistant built to run on local hardware with a local LLM. Single user — no auth.

## What it does

- **Chat interface** with streaming responses and tool use
- **Tools**: bash, web fetch, email, datetime, memory read/write, cron job management
- **Persistent conversation memory** across sessions (via `MEMORY.md` + per-file reads/writes)
- **Sandboxed bash execution** in a Docker container with a persistent home directory
- **Background cron jobs** that run tasks on a schedule and send results by email
- **Compact**: summarizes old messages so context doesn't blow up over long sessions

## Stack

- **Backend**: Python (FastAPI/uvicorn, asyncio), psycopg3 + Postgres
- **Frontend**: Svelte 5 + Vite, built to `dist/` and served as static files by the app
- **LLM**: OpenAI-compatible API ([local qwen3-8b](https://github.com/crackalamoo/qwen-crackalamoo)) or prod via env vars (comma-separated for multi-client failover)

## Setup

```sh
# Install dependencies
uv sync --group dev

# Create a .env file (see Environment below)

# Run database migrations manually (psql)
psql < src/backend/db/0001_initial_schema.sql
# ... repeat for each migration in src/backend/db/

# Start the dev server
uv run uvicorn --app-dir src app:app --host 0.0.0.0 --port 9174
```

The frontend is built separately with Vite (`src/frontend/`) into `dist/`, which the app serves as static files. The backend runs at port 9174.

## Environment

Set in a `.env` file at the repo root.

| Variable | Required | Description |
|---|---|---|
| `BOYNTON_DATABASE_URL` | yes | Postgres connection string, e.g. `postgresql:///boynton_bot` |
| `BOYNTON_MEMORY_DIR` | yes | Path to memory directory (can be `memory/` inside this repo, gitignored) |
| `BOYNTON_OPENAI_API_KEY` | yes | API key(s), comma-separated for multi-client failover |
| `BOYNTON_LLM_BASE_URL` | no | Base URL(s) for OpenAI-compatible API, comma-separated. Omit to use OpenAI directly. |
| `BOYNTON_LLM_MODEL` | no | Model name(s), comma-separated. Defaults to `gpt-5.4-mini`. |
| `BOYNTON_EMAIL_ADDRESS` | no | Sender address for `send_email` tool |
| `BOYNTON_EMAIL_PASSWORD` | no | SMTP password |
| `BOYNTON_EMAIL_SMTP_HOST` | no | SMTP host (default: `smtp.hostinger.com`) |
| `BOYNTON_EMAIL_SMTP_PORT` | no | SMTP port (default: `465`) |
| `BOYNTON_EMAIL_RECIPIENT` | no | Recipient address for `send_email` tool |

## Testing

```sh
uv run pytest
```

The test suite creates an isolated Postgres DB and memory dir, runs all tests, then cleans up. Requires a local Postgres instance with permission to create/drop databases.
