# Boynton Bot

Personal AI research assistant. Single user — no auth needed.

## Stack

Flask (port 9174) + nginx (port 80) + launchd. Svelte 5 + Vite frontend. Postgres via psycopg3. OpenAI-compatible LLM API — local qwen3-8b or prod via env vars. Always use `stream=True` — local qwen breaks otherwise.

## Memory

`MEMORY_DIR` env var (required). May use `memory/` in this repo (gitignored).

- `SOUL.md` — personality. Auto-injected. Read-only to the agent.
- `MEMORY.md` — index of other files. Auto-injected.
- Other files — agent reads/writes on demand via memory tools.

## Tools

`src/backend/tools/registry.py` contains all tools.
