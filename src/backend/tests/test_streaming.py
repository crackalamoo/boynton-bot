import json
import pytest
from unittest.mock import patch, AsyncMock
from psycopg.rows import dict_row

from backend.agent import CLIENTS, PRIMARY_MODEL, _execute_with_fallback, _persist_op, _compact
from backend.database import pool


def _stream_rounds(*rounds):
    """Returns a mock _stream_round that steps through each round on successive calls."""
    calls = iter(rounds)
    async def mock(*args, **kwargs):
        for event in next(calls):
            yield event
    return mock


async def _collect_sse(gen):
    return [json.loads(sse[len("data: "):].strip()) async for sse in gen
            if sse.startswith("data: ")]


@pytest.fixture
async def channel():
    ch = "test_stream"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


# --- streaming ---

async def test_basic_stream_emits_tokens_and_done(channel):
    mock = _stream_rounds([
        ("token", "Hello "),
        ("token", "world"),
        ("finish", ("Hello world", [], "stop")),
    ])
    with patch("backend.agent._stream_round", mock):
        events = await _collect_sse(_execute_with_fallback(channel, "hi"))

    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hello world"
    # Unmocked _execute_with_fallback always succeeds on CLIENTS[0] here — whether that's
    # actually "primary" depends on env, so derive the expectation rather than hardcode it.
    assert events[-1]["is_primary_model"] == (CLIENTS[0][1] == PRIMARY_MODEL)


async def test_basic_stream_persists_assistant_message(channel):
    mock = _stream_rounds([
        ("token", "Reply text"),
        ("finish", ("Reply text", [], "stop")),
    ])
    with patch("backend.agent._stream_round", mock):
        await _collect_sse(_execute_with_fallback(channel, "hi"))

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT content, model FROM messages WHERE session_id = %s AND role = 'assistant'",
                (channel,)
            )
            row = await cur.fetchone()
    assert row["content"] == "Reply text"
    assert row["model"] == CLIENTS[0][1]


async def test_tool_call_round_dispatches_and_continues(channel):
    mock = _stream_rounds(
        [("finish", ("", [{"id": "call_1", "name": "bash", "arguments": '{"command": "ls"}'}], "tool_calls"))],
        [("token", "Done"), ("finish", ("Done", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock), \
         patch("backend.agent.execute_tool", AsyncMock(return_value="file.txt")):
        events = await _collect_sse(_execute_with_fallback(channel, "run ls"))

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "done"
    assert events[types.index("tool_result")]["content"] == "file.txt"


async def test_tool_call_round_persists_tool_rows(channel):
    mock = _stream_rounds(
        [("finish", ("", [{"id": "call_1", "name": "bash", "arguments": '{"command": "ls"}'}], "tool_calls"))],
        [("finish", ("Done", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock), \
         patch("backend.agent.execute_tool", AsyncMock(return_value="file.txt")):
        await _collect_sse(_execute_with_fallback(channel, "run ls"))

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT role, content FROM messages WHERE session_id = %s ORDER BY id",
                (channel,)
            )
            rows = await cur.fetchall()

    roles = [r["role"] for r in rows]
    assert "tool_call" in roles
    assert "tool_result" in roles
    assert next(r for r in rows if r["role"] == "tool_result")["content"] == "file.txt"


async def test_tool_call_round_persists_model_on_llm_generated_rows_only(channel):
    mock = _stream_rounds(
        [("finish", ("", [{"id": "call_1", "name": "bash", "arguments": '{"command": "ls"}'}], "tool_calls"))],
        [("finish", ("Done", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock), \
         patch("backend.agent.execute_tool", AsyncMock(return_value="file.txt")):
        await _collect_sse(_execute_with_fallback(channel, "run ls"))

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT role, model FROM messages WHERE session_id = %s ORDER BY id",
                (channel,)
            )
            rows = await cur.fetchall()

    by_role = {}
    for r in rows:
        by_role.setdefault(r["role"], []).append(r["model"])

    assert all(m == CLIENTS[0][1] for m in by_role["assistant"])
    assert all(m == CLIENTS[0][1] for m in by_role["tool_call"])
    assert all(m is None for m in by_role["tool_result"])
    assert all(m is None for m in by_role["user"])


# --- compact ---

async def test_compact_returns_false_when_no_session():
    assert await _compact("nonexistent_channel") is False


async def test_compact_returns_false_when_no_messages(channel):
    assert await _compact(channel) is False


async def test_compact_summarizes_and_returns_true(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False})

    with patch("backend.agent._complete", AsyncMock(return_value="conversation summary")):
        result = await _compact(channel)

    assert result is True

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT summary FROM sessions WHERE id = %s", (channel,))
            row = await cur.fetchone()
    assert row["summary"] == "conversation summary"
