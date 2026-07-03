import asyncio
from openai import AsyncOpenAI, APIConnectionError
from dotenv import load_dotenv
from psycopg.rows import dict_row
from backend.database import pool
from backend.tools.registry import TOOLS, execute_tool
from backend.memory import load_soul, load_memory_index
from backend.job_queue import Job, JobQueue, stream_queue
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

_LLM_BASE_URLS = [u.strip() for u in (os.getenv("BOYNTON_LLM_BASE_URL") or "").split(",") if u.strip()]
_LLM_API_KEYS = [k.strip() for k in (os.getenv("BOYNTON_OPENAI_API_KEY") or "local").split(",") if k.strip()]
_LLM_MODELS = [m.strip() for m in (os.getenv("BOYNTON_LLM_MODEL") or "gpt-5.4-mini").split(",") if m.strip()]


def _build_clients() -> list[tuple[AsyncOpenAI, str]]:
    default_model = _LLM_MODELS[0] if _LLM_MODELS else "gpt-5.4-mini"
    if not _LLM_BASE_URLS:
        key = _LLM_API_KEYS[0] if _LLM_API_KEYS else "local"
        if key == "local":
            raise ValueError("BOYNTON_OPENAI_API_KEY not set")
        return [(AsyncOpenAI(api_key=key), default_model)]
    return [
        (
            AsyncOpenAI(
                api_key=_LLM_API_KEYS[i] if i < len(_LLM_API_KEYS) else _LLM_API_KEYS[-1],
                base_url=url,
            ),
            _LLM_MODELS[i] if i < len(_LLM_MODELS) else _LLM_MODELS[-1],
        )
        for i, url in enumerate(_LLM_BASE_URLS)
    ]


CLIENTS: list[tuple[AsyncOpenAI, str]] = _build_clients()


def _local_model() -> str | None:
    for i, url in enumerate(_LLM_BASE_URLS):
        if "localhost" in url or "127.0.0.1" in url:
            return _LLM_MODELS[i] if i < len(_LLM_MODELS) else _LLM_MODELS[-1]
    return None


# The model served from localhost, if any — not just whichever is first in CLIENTS,
# since list order is a config detail unrelated to whether an endpoint is actually local.
PRIMARY_MODEL: str | None = _local_model()


async def _complete(client: AsyncOpenAI, model: str, messages: list[dict[str, Any]]) -> str:
    response = await client.chat.completions.create(model=model, messages=messages, stream=False)
    return response.choices[0].message.content or ""


async def _stream_round(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools=None,
    max_tokens: int | None = None,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Stream one completion round.

    Yields ("token", str) for each text delta, ("reasoning", str) for each
    reasoning/thinking delta, then ("finish", (content, tool_calls, finish_reason)).
    """
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        stream=True,
        max_completion_tokens=max_tokens if max_tokens is not None else 2048,
        extra_body={"reasoning_effort": "low"},
    )
    if tools:
        kwargs["tools"] = tools
    accumulated_content = ""
    accumulated_tool_calls: dict[int, dict[str, str]] = {}
    finish_reason = "stop"
    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta.content:
            accumulated_content += delta.content
            yield ("token", delta.content)
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield ("reasoning", reasoning)
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


MEMORY_DIR = os.environ["BOYNTON_MEMORY_DIR"]  # required — filesystem path to memory files
SUMMARIZATION_THRESHOLD = 50_000  # tokens (approximate)
MAX_TOOL_ROUNDS = 15

SYSTEM_PROMPT = "You are a personal AI assistant."



def _estimate_tokens(messages):
    return sum((len(m.get("content") or "") + len(m.get("arguments") or "")) // 4 for m in messages)


async def _do_summarize(conn, cur, client, model: str, channel: str, session: dict[str, Any], unsummarized: list[dict[str, Any]]) -> dict[str, Any]:
    """Perform summarization of unsummarized messages and write the new summary to the sessions table.
    Returns the refreshed session row.
    """
    prior = f"Prior summary:\n{session['summary']}\n\n" if session["summary"] else ""
    lines = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in unsummarized)
    new_summary = await _complete(client, model, [{
        "role": "user",
        "content": f"Summarize this conversation concisely, preserving key facts and context:\n\n{prior}{lines}"
    }])
    await cur.execute(
        "UPDATE sessions SET summary = %s, summary_created_at = now() WHERE id = %s",
        (new_summary, channel)
    )
    await conn.commit()
    await cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
    return await cur.fetchone()


async def _compact(channel: str) -> bool:
    """Force summarization of the current conversation for this channel.

    Uses the same DB + summarization logic as the automatic path in _build_context.
    Returns True if summarization was performed, False if there was nothing to summarize.
    """
    client, model = CLIENTS[0]
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
            session = await cur.fetchone()

            if session is None:
                return False

            # Fetch unsummarized messages (same logic as _build_context)
            if session["summary_created_at"]:
                await cur.execute(
                    """SELECT role, content, arguments FROM messages
                       WHERE session_id = %s AND created_at > %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"])
                )
            else:
                await cur.execute(
                    "SELECT role, content, arguments FROM messages WHERE session_id = %s AND NOT hidden ORDER BY id ASC",
                    (channel,)
                )
            unsummarized = await cur.fetchall()

            if not unsummarized:
                return False

            await _do_summarize(conn, cur, client, model, channel, session, unsummarized)
            return True


def _reconstruct_messages(
    rows: list[dict[str, Any]], start_counter: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Reconstruct OpenAI-compatible messages (including `tool_calls`-carrying assistant
    messages and interleaved `tool` role messages) from raw `messages` table rows
    (role, content, tool_name, arguments — in `id` order).

    `start_counter` seeds the synthetic `tool_call` id counter. Pass the returned
    counter from one call as the `start_counter` of the next when reconstructing two
    row ranges that will be concatenated into the same message list (e.g. a stored
    prompt followed by a stored response) — otherwise both ranges mint colliding
    `call_0`, `call_1`, ... ids.

    Returns (messages, next_counter).
    """
    context_messages: list[dict[str, Any]] = []
    tc_counter = start_counter
    pending_ids: list[str] = []
    for m in rows:
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
    return context_messages, tc_counter


async def build_training_example(message_id: int) -> dict[str, Any]:
    """Reconstruct (prompt, response) for the turn ending in the given assistant message.

    `message_id` must be the id of the final assistant message of a turn — the one with
    no trailing `tool_call` rows, i.e. what's actually displayed as "the reply" in the
    chat UI. Raises ValueError if the message doesn't exist, isn't an assistant message,
    isn't the final one of its turn, has no preceding user message, or wasn't generated
    by PRIMARY_MODEL.

    Returns {"prompt": [...], "response": [...]} in the OpenAI-message-list shape:
    - `prompt` is the full context up to and including the preceding user message (same
      shape `_build_context` builds — system prompt, soul, memory index, summary if
      present, prior turns).
    - `response` is the full turn being judged: everything from right after the
      preceding user message through `message_id`, inclusive.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM messages WHERE id = %s", (message_id,))
            final_msg = await cur.fetchone()
            if final_msg is None:
                raise ValueError(f"no message with id {message_id}")
            if final_msg["role"] != "assistant":
                raise ValueError(f"message {message_id} is not an assistant message")
            if PRIMARY_MODEL is None or final_msg["model"] != PRIMARY_MODEL:
                raise ValueError(
                    f"message {message_id} was not generated by the primary model "
                    f"(model={final_msg['model']!r}, primary={PRIMARY_MODEL!r})"
                )
            channel = final_msg["session_id"]

            await cur.execute(
                "SELECT role FROM messages WHERE session_id = %s AND id > %s ORDER BY id ASC LIMIT 1",
                (channel, message_id),
            )
            next_row = await cur.fetchone()
            if next_row is not None and next_row["role"] == "tool_call":
                raise ValueError(f"message {message_id} is not the final assistant message of its turn")

            await cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
            session = await cur.fetchone()

            await cur.execute(
                """SELECT id FROM messages
                   WHERE session_id = %s AND role = 'user' AND id <= %s
                   ORDER BY id DESC LIMIT 1""",
                (channel, message_id),
            )
            preceding_user = await cur.fetchone()
            if preceding_user is None:
                raise ValueError(f"no preceding user message found for message {message_id}")
            preceding_user_id = preceding_user["id"]

            if session["summary_created_at"]:
                await cur.execute(
                    """SELECT role, content, tool_name, arguments FROM messages
                       WHERE session_id = %s AND created_at > %s AND id <= %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"], preceding_user_id),
                )
            else:
                await cur.execute(
                    """SELECT role, content, tool_name, arguments FROM messages
                       WHERE session_id = %s AND id <= %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, preceding_user_id),
                )
            prompt_rows = await cur.fetchall()

            await cur.execute(
                """SELECT role, content, tool_name, arguments FROM messages
                   WHERE session_id = %s AND id > %s AND id <= %s AND NOT hidden
                   ORDER BY id ASC""",
                (channel, preceding_user_id, message_id),
            )
            response_rows = await cur.fetchall()

            prompt = [{"role": "system", "content": SYSTEM_PROMPT}]
            soul = load_soul()
            if soul:
                prompt.append({"role": "system", "content": soul})
            memory_index = load_memory_index()
            if memory_index:
                prompt.append({"role": "system", "content": f"[Memory index]\n{memory_index}"})
            if session["summary"]:
                prompt.append({"role": "system", "content": f"[Summary of earlier conversation]: {session['summary']}"})
            prompt_messages, tc_counter = _reconstruct_messages(prompt_rows)
            prompt += prompt_messages

            response, _ = _reconstruct_messages(response_rows, start_counter=tc_counter)

    return {"prompt": prompt, "response": response}


async def _build_context(client, model: str, channel: str, user_message: str) -> tuple[list[dict[str, Any]], bool]:
    """Read DB to build the LLM context list, including inline summarization if needed.

    Returns (context_messages, did_summarize).
    Does NOT write anything except a potential summarization update to sessions.
    The user_message is appended manually since it is not yet in the DB.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Get session for summary info
            await cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
            session = await cur.fetchone()

            # Default session if channel has no prior session
            if session is None:
                session = {"summary": None, "summary_created_at": None}

            did_summarize = False

            # Check whether summarization is needed
            if session["summary_created_at"]:
                await cur.execute(
                    """SELECT role, content, arguments FROM messages
                       WHERE session_id = %s AND created_at > %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"])
                )
            else:
                await cur.execute(
                    "SELECT role, content, arguments FROM messages WHERE session_id = %s AND NOT hidden ORDER BY id ASC",
                    (channel,)
                )
            unsummarized = await cur.fetchall()
            # Note: user_message is NOT in DB yet, so no [:-1] needed

            if _estimate_tokens(unsummarized) > SUMMARIZATION_THRESHOLD:
                session = await _do_summarize(conn, cur, client, model, channel, session, unsummarized)
                did_summarize = True

            # Build context: system prompt + optional summary + messages after summary cutoff
            if session["summary_created_at"]:
                await cur.execute(
                    """SELECT role, content, tool_name, arguments FROM messages
                       WHERE session_id = %s AND created_at > %s AND NOT hidden
                       ORDER BY id ASC""",
                    (channel, session["summary_created_at"])
                )
            else:
                await cur.execute(
                    "SELECT role, content, tool_name, arguments FROM messages WHERE session_id = %s AND NOT hidden ORDER BY id ASC",
                    (channel,)
                )
            recent = await cur.fetchall()

            context = [{"role": "system", "content": SYSTEM_PROMPT}]
            soul = load_soul()
            if soul:
                context.append({"role": "system", "content": soul})
            memory_index = load_memory_index()
            if memory_index:
                context.append({"role": "system", "content": f"[Memory index]\n{memory_index}"})
            if session["summary"]:
                context.append({"role": "system", "content": f"[Summary of earlier conversation]: {session['summary']}"})
            context_messages, _ = _reconstruct_messages(recent)
            context += context_messages

            # User message is not in DB yet — append manually
            context.append({"role": "user", "content": user_message})

    return context, did_summarize


async def _execute(
    client,
    model: str,
    channel: str,
    context: list[dict[str, Any]],
    did_summarize: bool,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    """LLM + tool loop generator.

    - `context` is the already-built LLM context (from _build_context), including the
      not-yet-persisted user_message appended at the end. This function does NOT read
      the DB.
    - Runs the full LLM + tool loop, persisting every op immediately via `_persist_op`
      as it happens (assistant messages, tool calls, tool results).
    - Yields SSE strings live as events happen.
    """
    tool_context = list(context)
    tool_called = False
    n_tool_calls = 0
    final_message_id: int | None = None
    while True:
        n_tool_calls += 1
        tools = TOOLS if n_tool_calls <= MAX_TOOL_ROUNDS else None
        round_content: list[str] = []
        tool_calls = []
        finish_reason = "stop"
        async for kind, value in _stream_round(client, model, tool_context, tools=tools, max_tokens=max_tokens):
            if kind == "token":
                round_content.append(value)
                yield "data: " + json.dumps({"type": "token", "content": value}) + "\n\n"
            elif kind == "reasoning":
                yield "data: " + json.dumps({"type": "reasoning", "content": value}) + "\n\n"
            else:
                _, tool_calls, finish_reason = value

        text = "".join(round_content)

        # Tool calls are handled whenever present, regardless of finish_reason —
        # a "length" round can still carry a complete, valid tool call alongside
        # trailing text that got cut off elsewhere. Validity is judged per call.
        if tool_calls:
            # Assistant messages that carry tool_calls are never hidden.
            await _persist_op(channel, {"op": "assistant_msg", "content": text, "hidden": False, "model": model})

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": text}
            assistant_msg["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls
            ]
            tool_context.append(assistant_msg)
            for tc in tool_calls:
                # A malformed/truncated call (qwen's blank-name marker, or a
                # gpt-5.4-mini call whose arguments got cut off mid-JSON) must
                # not silently become "called with no arguments" — capture the
                # parse failure and surface it as an invalid call below, same
                # as any other validation failure.
                parse_error: Exception | None = None
                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError as e:
                    args = {}
                    parse_error = e

                yield "data: " + json.dumps({"type": "tool_call", "name": tc["name"], "arguments": args}) + "\n\n"
                await _persist_op(channel, {"op": "tool_call", "tool_name": tc["name"], "arguments": args, "model": model})
                try:
                    if parse_error is not None:
                        raise ValueError(f"arguments were not valid JSON ({parse_error})")
                    if not tc["name"]:
                        raise ValueError(
                            "no tool name/arguments could be recovered — the tool call was "
                            "malformed or got cut off before it finished generating"
                        )
                    result = await execute_tool(tc["name"], args)
                except (ValueError, KeyError, TypeError) as e:
                    # An unknown/blank tool name (malformed or truncated
                    # generation) or a missing/wrong-type argument. Report it
                    # back to the model as a normal tool result instead of
                    # crashing the turn — it has what it needs to retry with
                    # a corrected call.
                    result = f"Invalid tool call: {e}"
                yield "data: " + json.dumps({"type": "tool_result", "content": result}) + "\n\n"
                await _persist_op(channel, {"op": "tool_result", "tool_name": tc["name"], "content": result})
                tool_context.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            tool_called = True
            continue

        final_message_id = await _persist_op(channel, {"op": "assistant_msg", "content": text, "hidden": False, "model": model})
        break

    yield "data: " + json.dumps({
        "type": "done", "summarized": did_summarize, "tool_called": tool_called, "message_id": final_message_id,
        "is_primary_model": model == PRIMARY_MODEL,
    }) + "\n\n"


async def _run_with_fallback(
    channel: str,
    context: list[dict[str, Any]],
    did_summarize: bool = False,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    """Run `_execute` over `CLIENTS` in order, falling back to the next client on a
    connection error that happened before anything was committed for this turn.
    """
    last_exc: Exception | None = None
    for client, model in CLIENTS:
        gen = _execute(client, model, channel, context, did_summarize, max_tokens=max_tokens)
        committed = False
        try:
            async for event in gen:
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


async def _execute_with_fallback(
    channel: str,
    user_message: str,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    client0, model0 = CLIENTS[0]
    context, did_summarize = await _build_context(client0, model0, channel, user_message)

    await _persist_op(channel, {"op": "ensure_session", "channel": channel})
    await _persist_op(channel, {"op": "user_msg", "content": user_message, "hidden": False})

    async for event in _run_with_fallback(channel, context, did_summarize, max_tokens=max_tokens):
        yield event


async def _run_chat_job(channel: str, job: Job) -> None:
    """JobQueue handler for chat jobs (covers both interactive chat and background turns).

    If `job.sse_queue` is set, SSE events are forwarded to it for a live response
    (interactive chat). If it is None, the generator is simply drained (background job).
    """
    q = job.sse_queue
    try:
        gen = _execute_with_fallback(channel, job.user_message or "", max_tokens=job.max_tokens)
        if q is None:
            async for _ in gen:
                pass
        else:
            async for sse in gen:
                await q.put(sse)
    except Exception as e:
        if q is not None:
            await q.put("data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n")
        else:
            logger.exception(f"Background job error on channel {channel!r}")
    finally:
        if q is not None:
            await q.put(None)  # sentinel


async def _run_compact_job(channel: str, job: Job) -> None:
    result_queue = job.result_queue
    assert result_queue is not None
    try:
        did_compact = await _compact(channel)
        await result_queue.put((did_compact, None))
    except Exception as e:
        await result_queue.put((False, e))


async def _persist_op(channel: str, write: dict[str, Any]) -> int | None:
    """Persist a single op immediately, in its own connection/transaction.

    This is the ONE persistence primitive. Every op is written unconditionally
    and durably the moment it happens — no buffering, no batching.

    Op shapes:
      {"op": "ensure_session", "channel": channel}
      {"op": "user_msg", "content": "...", "hidden": bool}
      {"op": "assistant_msg", "content": "...", "hidden": bool, "model": str | None}
      {"op": "tool_call", "tool_name": "...", "arguments": {...}, "model": str | None}   # arguments is dict
      {"op": "tool_result", "tool_name": "...", "content": "..."}

    `model` is only meaningful for `assistant_msg`/`tool_call`; omit for other ops
    (defaults to NULL).

    `ensure_session` uses ON CONFLICT DO NOTHING, so it is safe to call repeatedly /
    out of order / multiple times for the same channel.

    Returns the inserted `messages.id` for ops that insert a message row, or None for
    `ensure_session`.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            op = write["op"]
            if op == "ensure_session":
                await cur.execute(
                    "INSERT INTO sessions (id, type) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (channel, channel)
                )
                await conn.commit()
                return None
            elif op == "user_msg":
                await cur.execute(
                    "INSERT INTO messages (session_id, role, content, hidden) VALUES (%s, %s, %s, %s) RETURNING id",
                    (channel, "user", write["content"], write["hidden"])
                )
            elif op == "assistant_msg":
                await cur.execute(
                    "INSERT INTO messages (session_id, role, content, hidden, model) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (channel, "assistant", write["content"], write["hidden"], write.get("model"))
                )
            elif op == "tool_call":
                await cur.execute(
                    "INSERT INTO messages (session_id, role, tool_name, arguments, hidden, model) VALUES (%s, %s, %s, %s::jsonb, FALSE, %s) RETURNING id",
                    (channel, "tool_call", write["tool_name"], json.dumps(write["arguments"]), write.get("model"))
                )
            elif op == "tool_result":
                await cur.execute(
                    "INSERT INTO messages (session_id, role, tool_name, content, hidden) VALUES (%s, %s, %s, %s, FALSE) RETURNING id",
                    (channel, "tool_result", write["tool_name"], write["content"])
                )
            else:
                raise ValueError(f"Unknown op: {op!r}")
            row = await cur.fetchone()
            await conn.commit()
            return row[0] if row else None


# Correction-drafting is fire-and-forget from the API's point of view (triggered by a
# thumbs-down note, polled for completion). Keep a strong reference to each task so it
# isn't garbage-collected mid-flight; the done callback discards it once finished.
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _draft_correction(example_id: int) -> None:
    """Draft a corrected response for a thumbs-down training example, in an isolated
    conversation (its own fresh session, not `web`, not reusing any existing chat
    history) that goes through the same LLM+tool pipeline as a normal turn — including
    real tool calls if the correction needs them.

    Feeds the original prompt, the original (bad) response, and the user's note, then
    asks for a corrected turn. Writes the result back as `correction` with
    `correction_status = 'drafted'` on success, or `correction_status = 'error'` if the
    drafting turn itself fails — never leaves the row stuck on 'drafting'.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM training_examples WHERE id = %s", (example_id,))
            row = await cur.fetchone()
    if row is None:
        logger.error(f"_draft_correction: no training_examples row with id {example_id}")
        return

    channel = f"training-correction-{example_id}"
    correction_request = (
        "The response above was marked as incorrect by the user. "
        f"Their note on what was wrong: {row['note']}\n\n"
        "Produce a corrected response. Actually call tools for real if the correction "
        "requires it (e.g. re-fetching a page to get accurate information), then give "
        "an accurate final answer."
    )
    context = list(row["prompt"]) + list(row["response"]) + [{"role": "user", "content": correction_request}]

    try:
        await _persist_op(channel, {"op": "ensure_session", "channel": channel})
        root_id = await _persist_op(channel, {"op": "user_msg", "content": correction_request, "hidden": False})

        async for _ in _run_with_fallback(channel, context):
            pass

        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """SELECT role, content, tool_name, arguments FROM messages
                       WHERE session_id = %s AND id > %s ORDER BY id ASC""",
                    (channel, root_id),
                )
                correction_rows = await cur.fetchall()
        # `correction` is stored in the same shape as `response` (design decision #7),
        # which continues the prompt's tool_call id counter rather than restarting at
        # 0 — otherwise `prompt + correction` (as used for a future DPO export, mirroring
        # `prompt + response`) could mint colliding ids if both contain tool calls.
        start_counter = sum(len(m.get("tool_calls") or []) for m in row["prompt"])
        correction, _ = _reconstruct_messages(correction_rows, start_counter=start_counter)

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE training_examples SET correction = %s::jsonb, correction_status = 'drafted' WHERE id = %s",
                    (json.dumps(correction), example_id),
                )
                await conn.commit()
    except Exception:
        logger.exception(f"Correction drafting failed for training_examples id {example_id}")
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE training_examples SET correction_status = 'error' WHERE id = %s",
                    (example_id,),
                )
                await conn.commit()


class Agent:
    def __init__(self):
        self._jobs = JobQueue(run_chat=_run_chat_job, run_compact=_run_compact_job)

    async def get_history(
        self,
        channel: str,
        include_hidden: bool = False,
        before_id: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT summary, summary_created_at FROM sessions WHERE id = %s", (channel,))
                session = await cur.fetchone()
                if session is None:
                    return {"messages": [], "summary_created_at": None, "summary": None, "has_more": False}

                summary_created_at = session["summary_created_at"]

                hidden_clause = "" if include_hidden else "AND NOT hidden"
                before_clause = "AND id < %s" if before_id is not None else ""
                # Page starts must land exactly on a role='user' row so that a turn (user +
                # its assistant/tool_call/tool_result rows) is never split across a page
                # boundary — parseHistory groups rows into turns and can't reassemble a
                # fragmented one from two separately-fetched pages.
                cursor_params: tuple[Any, ...] = (channel, before_id) if before_id is not None else (channel,)
                await cur.execute(
                    f"SELECT id FROM messages WHERE session_id = %s {hidden_clause} {before_clause} "
                    f"AND role = 'user' ORDER BY id DESC LIMIT %s",
                    (*cursor_params, limit),
                )
                user_row_ids = [r["id"] for r in await cur.fetchall()]

                if not user_row_ids:
                    return {
                        "messages": [],
                        "summary_created_at": summary_created_at.isoformat() if summary_created_at else None,
                        "summary": session["summary"],
                        "has_more": False,
                    }

                page_start_id = user_row_ids[-1]

                await cur.execute(
                    f"SELECT id FROM messages WHERE session_id = %s {hidden_clause} "
                    f"AND role = 'user' AND id < %s LIMIT 1",
                    (channel, page_start_id),
                )
                has_more = await cur.fetchone() is not None

                upper_bound_clause = "AND id < %s" if before_id is not None else ""
                upper_bound_params: tuple[Any, ...] = (before_id,) if before_id is not None else ()
                await cur.execute(
                    f"SELECT id, role, content, tool_name, arguments, hidden, created_at, model FROM messages "
                    f"WHERE session_id = %s {hidden_clause} AND id >= %s {upper_bound_clause} ORDER BY id ASC",
                    (channel, page_start_id, *upper_bound_params)
                )
                rows = await cur.fetchall()

                messages = [
                    {
                        "id": r["id"],
                        "role": r["role"],
                        "content": r["content"],
                        "tool_name": r["tool_name"],
                        "arguments": r["arguments"],
                        "hidden": r["hidden"],
                        "created_at": r["created_at"].isoformat(),
                        "is_primary_model": PRIMARY_MODEL is not None and r["model"] == PRIMARY_MODEL,
                    }
                    for r in rows
                ]

                return {
                    "messages": messages,
                    "summary_created_at": summary_created_at.isoformat() if summary_created_at else None,
                    "summary": session["summary"],
                    "has_more": has_more,
                }

    async def clear(self, channel: str):
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM messages WHERE session_id = %s", (channel,))
                await cur.execute(
                    "UPDATE sessions SET summary = NULL, summary_created_at = NULL WHERE id = %s",
                    (channel,)
                )

    async def submit_chat(self, channel: str, user_message: str, max_tokens: int | None = None) -> "asyncio.Queue[str | None]":
        """Enqueue a chat job and return the queue its SSE events will be written to."""
        return await self._jobs.submit_chat(channel, user_message, max_tokens=max_tokens)

    async def submit_background(
        self,
        channel: str,
        prompt: str,
    ) -> None:
        """Enqueue a fire-and-forget chat job (used by the cron scheduler)."""
        await self._jobs.submit_background(channel, prompt)

    async def submit_compact(self, channel: str) -> bool:
        """Enqueue a compact job and wait until it completes.

        Returns True if summarization was performed, False if there was nothing to summarize.
        """
        return await self._jobs.submit_compact(channel)

    def stream_queue(self, q: "asyncio.Queue[str | None]") -> AsyncGenerator[str, None]:
        """SSE generator that awaits a job-specific queue until the None sentinel."""
        return stream_queue(q)

    async def record_feedback(self, message_id: int, label: str) -> dict[str, Any]:
        """Materialize a thumbs up/down into `training_examples`.

        Thumbs-up is immediate and final: `correction`/`correction_status` stay NULL.
        Thumbs-down is written immediately with `correction_status = 'pending'`; a note
        (added later via `add_feedback_note`) is what actually kicks off drafting.

        A second call for the same `message_id` overwrites the prior row (re-judging a
        message resets any note/correction/status it had) rather than accumulating
        conflicting rows.
        """
        example = await build_training_example(message_id)
        correction_status = "pending" if label == "down" else None
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """INSERT INTO training_examples (message_id, label, prompt, response, correction_status)
                       VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                       ON CONFLICT (message_id) DO UPDATE SET
                           label = EXCLUDED.label,
                           prompt = EXCLUDED.prompt,
                           response = EXCLUDED.response,
                           note = NULL,
                           correction = NULL,
                           correction_status = EXCLUDED.correction_status
                       RETURNING *""",
                    (message_id, label, json.dumps(example["prompt"]), json.dumps(example["response"]), correction_status),
                )
                row = await cur.fetchone()
                await conn.commit()
        return row

    async def get_feedback(self, example_id: int) -> dict[str, Any] | None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM training_examples WHERE id = %s", (example_id,))
                return await cur.fetchone()

    async def get_feedback_for_message(self, message_id: int) -> dict[str, Any] | None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM training_examples WHERE message_id = %s", (message_id,))
                return await cur.fetchone()

    async def add_feedback_note(self, example_id: int, note: str) -> dict[str, Any]:
        """Attach an optional freeform note to a thumbs-down row and kick off correction
        drafting in the background. Raises ValueError if there's no such thumbs-down row.
        """
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """UPDATE training_examples SET note = %s, correction_status = 'drafting'
                       WHERE id = %s AND label = 'down' RETURNING *""",
                    (note, example_id),
                )
                row = await cur.fetchone()
                await conn.commit()
        if row is None:
            raise ValueError(f"no thumbs-down training example with id {example_id}")
        _spawn_background(_draft_correction(example_id))
        return row

    async def resolve_feedback(
        self, example_id: int, action: str, correction: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Human approval gate for a drafted correction. `approve` accepts the drafted
        correction as-is, or `correction` if the human edited it. `reject` discards it
        (but keeps the row, with `correction_status = 'rejected'`, rather than deleting
        it silently).
        """
        if action == "approve":
            status = "approved"
        elif action == "reject":
            status = "rejected"
        else:
            raise ValueError(f"unknown action: {action!r}")
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if correction is not None:
                    await cur.execute(
                        "UPDATE training_examples SET correction = %s::jsonb, correction_status = %s WHERE id = %s RETURNING *",
                        (json.dumps(correction), status, example_id),
                    )
                else:
                    await cur.execute(
                        "UPDATE training_examples SET correction_status = %s WHERE id = %s RETURNING *",
                        (status, example_id),
                    )
                row = await cur.fetchone()
                await conn.commit()
        if row is None:
            raise ValueError(f"no training example with id {example_id}")
        return row

