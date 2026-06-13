from openai import OpenAI, APIConnectionError
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from backend.tools.registry import TOOLS, execute_tool
from backend.memory import load_soul, load_memory_index
import json
import os
import queue
import threading
from typing import Any, Callable, Generator

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

_LLM_BASE_URLS = [u.strip() for u in (os.getenv("LLM_BASE_URL") or "").split(",") if u.strip()]
_LLM_API_KEYS = [k.strip() for k in (os.getenv("OPENAI_API_KEY") or "local").split(",") if k.strip()]
_LLM_MODELS = [m.strip() for m in (os.getenv("LLM_MODEL") or "gpt-5.4-mini").split(",") if m.strip()]


def _build_clients() -> list[tuple[OpenAI, str]]:
    default_model = _LLM_MODELS[0] if _LLM_MODELS else "gpt-5.4-mini"
    if not _LLM_BASE_URLS:
        key = _LLM_API_KEYS[0] if _LLM_API_KEYS else "local"
        if key == "local":
            raise ValueError("OPENAI_API_KEY not set")
        return [(OpenAI(api_key=key), default_model)]
    return [
        (
            OpenAI(
                api_key=_LLM_API_KEYS[i] if i < len(_LLM_API_KEYS) else _LLM_API_KEYS[-1],
                base_url=url,
            ),
            _LLM_MODELS[i] if i < len(_LLM_MODELS) else _LLM_MODELS[-1],
        )
        for i, url in enumerate(_LLM_BASE_URLS)
    ]


CLIENTS: list[tuple[OpenAI, str]] = _build_clients()


def _complete(client: OpenAI, model: str, messages: list[dict[str, Any]]) -> str:
    kwargs: dict[str, Any] = dict(model=model, messages=messages, stream=True)
    chunks = client.chat.completions.create(**kwargs)
    return "".join(c.choices[0].delta.content or "" for c in chunks)


def _stream_round(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools=None,
    max_tokens: int | None = None,
) -> Generator[tuple[str, Any], None, None]:
    """Stream one completion round.

    Yields ("token", str) for each text delta, then ("finish", (content, tool_calls, finish_reason)).
    """
    kwargs: dict[str, Any] = dict(model=model, messages=messages, stream=True, max_completion_tokens=max_tokens if max_tokens is not None else 2048)
    if tools:
        kwargs["tools"] = tools
    accumulated_content = ""
    accumulated_tool_calls: dict[int, dict[str, str]] = {}
    finish_reason = "stop"
    for chunk in client.chat.completions.create(**kwargs):
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta.content:
            accumulated_content += delta.content
            yield ("token", delta.content)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                i = tc.index
                if i not in accumulated_tool_calls:
                    accumulated_tool_calls[i] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    accumulated_tool_calls[i]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        accumulated_tool_calls[i]["name"] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[i]["arguments"] += tc.function.arguments
    tool_calls = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls)]
    yield ("finish", (accumulated_content, tool_calls, finish_reason))


DB_URL = os.getenv("DATABASE_URL", "postgresql:///boynton_bot")
MEMORY_DIR = os.environ["MEMORY_DIR"]  # required — filesystem path to memory files
SUMMARIZATION_THRESHOLD = 100_000  # tokens (approximate)
MAX_TOOL_ROUNDS = 15

SYSTEM_PROMPT = "You are a personal AI assistant."

pool = ConnectionPool(DB_URL, open=True)



def _estimate_tokens(messages):
    return sum(len(m.get("content", "")) // 4 for m in messages)


def _do_summarize(conn, cur, client, model: str, channel: str, session: dict[str, Any], unsummarized: list[dict[str, Any]]) -> dict[str, Any]:
    """Perform summarization of unsummarized messages and write the new summary to the sessions table.
    Returns the refreshed session row.
    """
    prior = f"Prior summary:\n{session['summary']}\n\n" if session["summary"] else ""
    lines = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in unsummarized)
    new_summary = _complete(client, model, [{
        "role": "user",
        "content": f"Summarize this conversation concisely, preserving key facts and context:\n\n{prior}{lines}"
    }])
    cur.execute(
        "UPDATE sessions SET summary = %s, summary_created_at = now() WHERE id = %s",
        (new_summary, channel)
    )
    conn.commit()
    cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
    return cur.fetchone()


def _build_context(client, model: str, channel: str, user_message: str) -> tuple[list[dict[str, Any]], bool]:
    """Read DB to build the LLM context list, including inline summarization if needed.

    Returns (context_messages, did_summarize).
    Does NOT write anything except a potential summarization update to sessions.
    The user_message is appended manually since it is not yet in the DB.
    """
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get session for summary info
            cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
            session = cur.fetchone()

            # Default session if channel has no prior session
            if session is None:
                session = {"summary": None, "summary_created_at": None}

            did_summarize = False

            # Check whether summarization is needed
            if session["summary_created_at"]:
                cur.execute(
                    """SELECT role, content FROM messages
                       WHERE session_id = %s AND created_at > %s AND role IN ('user', 'assistant') AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"])
                )
            else:
                cur.execute(
                    "SELECT role, content FROM messages WHERE session_id = %s AND role IN ('user', 'assistant') AND NOT hidden ORDER BY id ASC",
                    (channel,)
                )
            unsummarized = cur.fetchall()
            # Note: user_message is NOT in DB yet, so no [:-1] needed

            if _estimate_tokens(unsummarized) > SUMMARIZATION_THRESHOLD:
                session = _do_summarize(conn, cur, client, model, channel, session, unsummarized)
                did_summarize = True

            # Build context: system prompt + optional summary + messages after summary cutoff
            if session["summary_created_at"]:
                cur.execute(
                    """SELECT role, content, tool_name, arguments FROM messages
                       WHERE session_id = %s AND created_at > %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"])
                )
            else:
                cur.execute(
                    "SELECT role, content, tool_name, arguments FROM messages WHERE session_id = %s AND NOT hidden ORDER BY id ASC",
                    (channel,)
                )
            recent = cur.fetchall()

            context = [{"role": "system", "content": SYSTEM_PROMPT}]
            soul = load_soul()
            if soul:
                context.append({"role": "system", "content": soul})
            memory_index = load_memory_index()
            if memory_index:
                context.append({"role": "system", "content": f"[Memory index]\n{memory_index}"})
            if session["summary"]:
                context.append({"role": "system", "content": f"[Summary of earlier conversation]: {session['summary']}"})
            # Reconstruct OpenAI-compatible messages including tool calls
            context_messages = []
            tc_counter = 0
            pending_ids: list[str] = []
            for m in recent:
                if m["role"] == "user":
                    context_messages.append({"role": "user", "content": m["content"] or ""})
                    pending_ids = []
                elif m["role"] == "assistant":
                    context_messages.append({"role": "assistant", "content": m["content"] or ""})
                    pending_ids = []
                elif m["role"] == "tool_call":
                    tc_id = f"call_{tc_counter}"
                    tc_counter += 1
                    last = context_messages[-1]
                    if "tool_calls" not in last:
                        last["tool_calls"] = []
                    last["tool_calls"].append({
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": m["tool_name"], "arguments": json.dumps(m["arguments"] or {})},
                    })
                    pending_ids.append(tc_id)
                elif m["role"] == "tool_result":
                    tc_id = pending_ids.pop(0)
                    context_messages.append({"role": "tool", "tool_call_id": tc_id, "content": m["content"] or ""})
            context += context_messages

            # User message is not in DB yet — append manually
            context.append({"role": "user", "content": user_message})

    return context, did_summarize


def _execute(
    client,
    model: str,
    channel: str,
    context: list[dict[str, Any]],
    did_summarize: bool,
    is_suppressed: Callable[[str], bool] | None,
    max_tokens: int | None = None,
) -> Generator[str, None, None]:
    """LLM + tool loop generator.

    - `context` is the already-built LLM context (from _build_context), including the
      not-yet-persisted user_message appended at the end. This function does NOT read
      the DB.
    - Runs the full LLM + tool loop, persisting every op immediately via `_persist_op`
      as it happens (assistant messages, tool calls, tool results).
    - `is_suppressed`, if provided, is called with the final round's text (only when no
      tool was called) to decide whether the final assistant_msg should be persisted as
      `hidden`. Only heartbeat callers pass this; normal chat passes None, so its
      assistant messages are never hidden.
    - Yields SSE strings live as events happen.
    """
    tool_context = list(context)
    tool_called = False
    n_tool_calls = 0
    while True:
        n_tool_calls += 1
        tools = TOOLS if n_tool_calls <= MAX_TOOL_ROUNDS else None
        round_content: list[str] = []
        tool_calls = []
        finish_reason = "stop"
        for kind, value in _stream_round(client, model, tool_context, tools=tools, max_tokens=max_tokens):
            if kind == "token":
                round_content.append(value)
                yield "data: " + json.dumps({"type": "token", "content": value}) + "\n\n"
            else:
                _, tool_calls, finish_reason = value

        text = "".join(round_content)

        if finish_reason == "tool_calls" and tool_calls:
            # Assistant messages that carry tool_calls are never hidden.
            _persist_op(channel, {"op": "assistant_msg", "content": text, "hidden": False})

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": text}
            assistant_msg["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls
            ]
            tool_context.append(assistant_msg)
            for tc in tool_calls:
                args = json.loads(tc["arguments"] or "{}")
                yield "data: " + json.dumps({"type": "tool_call", "name": tc["name"], "arguments": args}) + "\n\n"
                _persist_op(channel, {"op": "tool_call", "tool_name": tc["name"], "arguments": args})
                result = execute_tool(tc["name"], args)
                yield "data: " + json.dumps({"type": "tool_result", "content": result}) + "\n\n"
                _persist_op(channel, {"op": "tool_result", "tool_name": tc["name"], "content": result})
                tool_context.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            tool_called = True
            continue

        hidden = not tool_called and is_suppressed is not None and is_suppressed(text)
        _persist_op(channel, {"op": "assistant_msg", "content": text, "hidden": hidden})
        break

    yield "data: " + json.dumps({"type": "done", "summarized": did_summarize, "tool_called": tool_called}) + "\n\n"


def _execute_with_fallback(
    channel: str,
    user_message: str,
    max_tokens: int | None = None,
    is_suppressed: Callable[[str], bool] | None = None,
) -> Generator[str, None, None]:
    client0, model0 = CLIENTS[0]
    context, did_summarize = _build_context(client0, model0, channel, user_message)

    _persist_op(channel, {"op": "ensure_session", "channel": channel})
    # Heartbeat check-in prompts are NEVER hidden — only the assistant's HEARTBEAT_OK
    # reply can be hidden.
    _persist_op(channel, {"op": "user_msg", "content": user_message, "hidden": False})

    last_exc: Exception | None = None
    for client, model in CLIENTS:
        gen = _execute(client, model, channel, context, did_summarize, is_suppressed, max_tokens=max_tokens)
        committed = False
        try:
            for event in gen:
                committed = True
                yield event
            return
        except APIConnectionError as e:
            if committed:
                raise
            last_exc = e
    if last_exc:
        raise last_exc
    raise RuntimeError("No LLM servers available")


def _persist_op(channel: str, write: dict[str, Any]) -> None:
    """Persist a single op immediately, in its own connection/transaction.

    This is the ONE persistence primitive. Every op is written unconditionally
    and durably the moment it happens — no buffering, no batching.

    Op shapes:
      {"op": "ensure_session", "channel": channel}
      {"op": "user_msg", "content": "...", "hidden": bool}
      {"op": "assistant_msg", "content": "...", "hidden": bool}
      {"op": "tool_call", "tool_name": "...", "arguments": {...}}   # arguments is dict
      {"op": "tool_result", "tool_name": "...", "content": "..."}

    `ensure_session` uses ON CONFLICT DO NOTHING, so it is safe to call repeatedly /
    out of order / multiple times for the same channel.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            op = write["op"]
            if op == "ensure_session":
                cur.execute(
                    "INSERT INTO sessions (id, type) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (channel, channel)
                )
            elif op == "user_msg":
                cur.execute(
                    "INSERT INTO messages (session_id, role, content, hidden) VALUES (%s, %s, %s, %s)",
                    (channel, "user", write["content"], write["hidden"])
                )
            elif op == "assistant_msg":
                cur.execute(
                    "INSERT INTO messages (session_id, role, content, hidden) VALUES (%s, %s, %s, %s)",
                    (channel, "assistant", write["content"], write["hidden"])
                )
            elif op == "tool_call":
                cur.execute(
                    "INSERT INTO messages (session_id, role, tool_name, arguments, hidden) VALUES (%s, %s, %s, %s::jsonb, FALSE)",
                    (channel, "tool_call", write["tool_name"], json.dumps(write["arguments"]))
                )
            elif op == "tool_result":
                cur.execute(
                    "INSERT INTO messages (session_id, role, tool_name, content, hidden) VALUES (%s, %s, %s, %s, FALSE)",
                    (channel, "tool_result", write["tool_name"], write["content"])
                )
            else:
                raise ValueError(f"Unknown op: {op!r}")
            conn.commit()


class Agent:
    def __init__(self):
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._queues: dict[str, queue.Queue[str | None]] = {}

    def get_history(self, channel: str, include_hidden: bool = False) -> dict[str, Any]:
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT summary_created_at FROM sessions WHERE id = %s", (channel,))
                session = cur.fetchone()
                if session is None:
                    return {"messages": [], "summary_created_at": None}

                summary_created_at = session["summary_created_at"]

                hidden_clause = "" if include_hidden else "AND NOT hidden"
                cur.execute(
                    f"SELECT role, content, tool_name, arguments, hidden, created_at FROM messages "
                    f"WHERE session_id = %s {hidden_clause} ORDER BY id ASC",
                    (channel,)
                )
                rows = cur.fetchall()

                messages = [
                    {
                        "role": r["role"],
                        "content": r["content"],
                        "tool_name": r["tool_name"],
                        "arguments": r["arguments"],
                        "hidden": r["hidden"],
                        "created_at": r["created_at"].isoformat(),
                    }
                    for r in rows
                ]

                return {
                    "messages": messages,
                    "summary_created_at": summary_created_at.isoformat() if summary_created_at else None,
                }

    def clear(self, channel: str):
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages WHERE session_id = %s", (channel,))
                cur.execute(
                    "UPDATE sessions SET summary = NULL, summary_created_at = NULL WHERE id = %s",
                    (channel,)
                )

    def compact(self, channel: str) -> bool:
        """Force summarization of the current conversation for this channel.

        Uses the same DB + summarization logic as the automatic path in _build_context.
        Returns True if summarization was performed, False if there was nothing to summarize.
        """
        client, model = CLIENTS[0]
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
                session = cur.fetchone()

                if session is None:
                    return False

                # Fetch unsummarized messages (same logic as _build_context)
                if session["summary_created_at"]:
                    cur.execute(
                        """SELECT role, content FROM messages
                           WHERE session_id = %s AND created_at > %s AND role IN ('user', 'assistant') AND NOT hidden
                           ORDER BY id ASC""",
                        (channel, session["summary_created_at"])
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE session_id = %s AND role IN ('user', 'assistant') AND NOT hidden ORDER BY id ASC",
                        (channel,)
                    )
                unsummarized = cur.fetchall()

                if not unsummarized:
                    return False

                _do_summarize(conn, cur, client, model, channel, session, unsummarized)
                return True

    def submit(self, channel: str, user_message: str, max_tokens: int | None = None) -> bool:
        """Start a background daemon thread that runs _execute and feeds self._queues[channel].

        Returns False if the channel is already running, True otherwise.
        """
        with self._lock:
            if channel in self._running:
                return False
            self._running.add(channel)
            q: queue.Queue[str | None] = queue.Queue()
            self._queues[channel] = q

        def _worker():
            try:
                for sse in _execute_with_fallback(channel, user_message, max_tokens=max_tokens):
                    q.put(sse)
            except Exception as e:
                q.put("data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n")
            finally:
                with self._lock:
                    self._running.discard(channel)
                q.put(None)  # sentinel

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True

    def stream(self, channel: str) -> Generator[str, None, None]:
        """SSE generator for the web UI. Reads from _queues[channel] until None sentinel."""
        q = self._queues.get(channel)
        if q is None:
            yield "data: " + json.dumps({"type": "error", "message": f"No active stream for channel {channel!r}"}) + "\n\n"
            return
        while True:
            item = q.get()
            if item is None:
                return
            yield item

    def run_collect(
        self,
        channel: str,
        user_message: str,
        max_tokens: int | None = None,
        is_suppressed: Callable[[str], bool] | None = None,
    ) -> tuple[list[str], bool]:
        """Synchronous execution for heartbeat. Collects all SSE strings and returns
        (events, tool_called).

        `is_suppressed`, if provided, is called with the final reply text (when no tool
        was called) to decide whether that assistant message should be persisted as
        hidden. Intended for heartbeat callers only.

        Persistence already happens internally inside _execute_with_fallback as it
        streams — there is nothing left to persist after this returns.
        """
        events = list(_execute_with_fallback(channel, user_message, max_tokens=max_tokens, is_suppressed=is_suppressed))

        tool_called = False
        for item in events:
            try:
                raw = item
                if raw.startswith("data: "):
                    raw = raw[len("data: "):]
                payload = json.loads(raw.strip())
                if payload.get("type") == "done":
                    tool_called = bool(payload.get("tool_called"))
            except Exception:
                pass

        return events, tool_called

