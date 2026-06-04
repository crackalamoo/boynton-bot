# Boynton Bot

Personal AI research assistant. Single user — no auth needed.

## Architecture intent

The backend should split into an agent core (conversation, summarization, tools) and channel adapters (web UI, Telegram, etc.).

## Key constraints

- Always use `stream=True` when calling the LLM — the local qwen backend always streams regardless of the flag, so non-streaming calls will break with it.
- System prompt must stay stable across requests (no dynamic content injected into it) to maximize prompt cache hits.
- History is per-session (one per channel). Cross-channel context is handled via a separate memory layer — important facts are extracted and stored, then injected into any session's system prompt. Raw conversation history is never shared across channels.

## Planned but not yet built

- Postgres for persistent conversation history (per-session) and a memory layer (cross-session facts)
- Channel abstraction (Telegram, etc.)
- Tool calling loop for agentic behavior
- Subagent support (requires per-conversation history isolation first)
