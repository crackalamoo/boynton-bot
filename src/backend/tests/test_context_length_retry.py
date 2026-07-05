import httpx
import pytest
from openai import BadRequestError
from unittest.mock import AsyncMock, patch
from psycopg.rows import dict_row

from backend.agent import (
    NORMAL_MAX_PROMPT_TOKENS,
    _execute_with_fallback,
    _is_context_length_exceeded,
    _persist_op,
)
from backend.database import pool


def _bad_request_error(code: str | None = "context_length_exceeded") -> BadRequestError:
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    body = {
        "error": {
            "message": f"This model's maximum context length is {NORMAL_MAX_PROMPT_TOKENS} tokens. "
                       f"However, your messages resulted in {NORMAL_MAX_PROMPT_TOKENS + 5000} tokens.",
            "type": "invalid_request_error",
            "param": "messages",
            "code": code,
        }
    }
    response = httpx.Response(400, request=request, json=body)
    return BadRequestError("context length exceeded", response=response, body=body)


@pytest.fixture
async def channel():
    ch = "test_context_retry"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


# --- _is_context_length_exceeded unit tests ---

def test_detects_context_length_exceeded_code():
    assert _is_context_length_exceeded(_bad_request_error("context_length_exceeded")) is True


def test_ignores_other_error_codes():
    assert _is_context_length_exceeded(_bad_request_error("some_other_error")) is False


def test_handles_missing_body_gracefully():
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(400, request=request, text="not json")
    err = BadRequestError("boom", response=response, body=None)
    assert _is_context_length_exceeded(err) is False


# --- retry-after-compact integration ---

async def test_context_length_exceeded_triggers_compact_and_retry(channel):
    """First call to _stream_round raises context_length_exceeded; boynton-bot
    should force a compaction and retry the turn once, succeeding."""
    await _persist_op(channel, {"op": "user_msg", "content": "old backlog", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "old reply", "hidden": False})

    calls = {"n": 0}
    retry_contexts: list[list] = []

    async def fail_once_stream_round(client, model, tool_context, **kwargs):
        # Simulates qwen rejecting the first attempt with context_length_exceeded,
        # then succeeding once _execute_with_fallback compacts and retries.
        calls["n"] += 1
        if calls["n"] == 1:
            raise _bad_request_error()
            yield  # pragma: no cover
        retry_contexts.append(list(tool_context))
        yield ("finish", ("recovered reply", [], "stop"))

    with patch("backend.agent._stream_round", fail_once_stream_round), \
         patch("backend.agent._complete", AsyncMock(return_value="forced summary")):
        events = []
        async for sse in _execute_with_fallback(channel, "new message"):
            events.append(sse)

    assert calls["n"] == 2
    # the retried turn must still carry the actual user message, not just its
    # gist folded into the forced summary
    assert retry_contexts[0][-1] == {"role": "user", "content": "new message"}

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT summary FROM sessions WHERE id = %s", (channel,))
            session = await cur.fetchone()
            await cur.execute(
                "SELECT role, content FROM messages WHERE session_id = %s AND role = 'user' ORDER BY id",
                (channel,)
            )
            user_rows = await cur.fetchall()

    assert session["summary"] == "forced summary"  # _compact ran
    # the retry rebuilds context without re-persisting the user message
    assert [r["content"] for r in user_rows] == ["old backlog", "new message"]


async def test_non_context_length_bad_request_is_not_retried(channel):
    async def always_fails(*args, **kwargs):
        raise _bad_request_error("some_other_error")
        yield  # pragma: no cover

    with patch("backend.agent._stream_round", always_fails):
        with pytest.raises(BadRequestError):
            async for _ in _execute_with_fallback(channel, "hi"):
                pass
