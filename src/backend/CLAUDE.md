# Backend

## Agent loop (`agent.py`)

`_execute_with_fallback(channel, message)` streams SSE to the caller. It builds context from history, calls the LLM, and loops if the model requests tool calls — dispatching each tool, persisting the call/result pair, then feeding results back. Stops when the model returns a plain text response.

Multi-client failover: multiple `(client, model)` pairs can be configured via comma-separated env vars. On connection error the next client is tried in order.

## Job queue (`job_queue.py`)

Per-channel FIFO queue. Each channel gets one long-lived asyncio worker so concurrent requests to the same channel are serialized, not dropped or interleaved. Background cron jobs go through the same queue.

## Cron (`cron.py`)

Background asyncio task polls the DB every 60s. Two schedule types:

- `at` — fires once at a specific ISO datetime
- `cron` — repeating schedule via cron expression (`croniter`), using `last_run_at` (or `created_at` if never run) as the base

Cron jobs fire as normal agent turns so they get full tool use, memory, etc.

## Database (`database.py`)

Connection pool is created at import time with `open=False` and must be explicitly opened before use. In production this happens at app startup; in tests the `open_pool` session fixture does it.

See `db/CLAUDE.md` for the migration workflow.

## Compact

Summarizes old messages when context grows large. Stores the summary in `sessions.summary`, hides old messages, and injects the summary as a system message on subsequent turns.
