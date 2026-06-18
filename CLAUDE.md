# Boynton Bot

Personal AI research assistant. Single user — no auth needed.

## Stack

FastAPI/uvicorn (port 9174). Svelte 5 + Vite frontend, served as static files by the app itself. Postgres via psycopg3. OpenAI-compatible LLM API — local qwen3-8b or prod via env vars.

## Commands

```sh
uv run uvicorn --app-dir src app:app --host 0.0.0.0 --port 9174  # dev server
uv run pytest                                                      # test suite
cd src/frontend && npm run check                                   # frontend type-check
cd src/frontend && npm run build                                   # build frontend
```


## Environment

Required: `DATABASE_URL`, `MEMORY_DIR`, `OPENAI_API_KEY`. Optional: `LLM_BASE_URL`, `LLM_MODEL`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_RECIPIENT`. Comma-separate any of the LLM vars for multi-client failover.

## Memory

`MEMORY_DIR` env var (required). May use `memory/` in this repo (gitignored).

- `SOUL.md` — personality. Auto-injected. Read-only to the agent.
- `MEMORY.md` — index of other files. Auto-injected.
- Other files — agent reads/writes on demand via memory tools.

## Tools

`src/backend/tools/registry.py` — see `src/backend/tools/CLAUDE.md` for how to add tools.

## Testing

`uv run pytest` — creates an isolated Postgres DB and memory dir with a random suffix, runs all tests, then cleans up. Requires a local Postgres instance with permission to create/drop databases.

Tests live next to their source in `tests/` subfolders (`src/backend/tests/`, `src/backend/tools/tests/`). New tests go in the subfolder closest to the code they test.
