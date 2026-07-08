import httpx
import pytest
from openai import BadRequestError
from unittest.mock import AsyncMock, patch
from psycopg.rows import dict_row

from backend.agent import (
    CHARS_PER_TOKEN_ESTIMATE,
    NORMAL_MAX_PROMPT_TOKENS,
    SUMMARIZE_TOKEN_BUDGET,
    _budget_unsummarized_lines,
    _compact,
    _context_length_overage,
    _do_summarize,
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


# --- _context_length_overage unit tests ---

def test_context_length_overage_parses_real_numbers():
    # _bad_request_error() reports NORMAL_MAX_PROMPT_TOKENS + 5000 tokens used.
    assert _context_length_overage(_bad_request_error()) == 5000


def test_context_length_overage_returns_none_for_unparsable_message():
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    body = {"error": {"message": "something went wrong", "code": "context_length_exceeded"}}
    response = httpx.Response(400, request=request, json=body)
    err = BadRequestError("boom", response=response, body=body)
    assert _context_length_overage(err) is None


def test_context_length_overage_returns_none_for_missing_body():
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(400, request=request, text="not json")
    err = BadRequestError("boom", response=response, body=None)
    assert _context_length_overage(err) is None


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


# --- mid-turn recovery: compact prior turns without losing the active turn's own tool output ---

async def test_context_length_exceeded_after_a_tool_call_keeps_the_active_turn_intact(channel):
    """Rejection on a later round (after a tool call already ran this turn) must
    compact only prior turns — the active turn's own tool exchange should survive
    intact in the retried context, not get folded into the lossy summary too."""
    await _persist_op(channel, {"op": "user_msg", "content": "old backlog", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "old reply", "hidden": False})

    calls = {"n": 0}
    retry_contexts: list[list] = []

    async def stream_round(client, model, tool_context, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield ("finish", ("", [{"id": "call_0", "name": "lookup", "arguments": "{}"}], "tool_calls"))
        elif calls["n"] == 2:
            raise _bad_request_error()
            yield  # pragma: no cover
        else:
            retry_contexts.append(list(tool_context))
            yield ("finish", ("done", [], "stop"))

    with patch("backend.agent._stream_round", stream_round), \
         patch("backend.agent.execute_tool", AsyncMock(return_value="tool result data")), \
         patch("backend.agent._complete", AsyncMock(return_value="forced summary")):
        async for _ in _execute_with_fallback(channel, "new message"):
            pass

    assert calls["n"] == 3  # tool round, failed round, recovered round

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT summary FROM sessions WHERE id = %s", (channel,))
            session = await cur.fetchone()
    assert session["summary"] == "forced summary"  # prior turn got folded

    retry_context = retry_contexts[0]
    assert any(m.get("role") == "user" and m.get("content") == "new message" for m in retry_context)
    assert any(m.get("role") == "tool" and m.get("content") == "tool result data" for m in retry_context)


async def test_context_length_exceeded_truncates_active_turn_if_compacting_prior_turns_is_not_enough(channel):
    """If the active turn's own tool output is oversized enough on its own, compacting
    prior turns isn't sufficient — the active turn's own messages must then be
    progressively truncated (never dropped), same as the summarization-input path."""
    calls = {"n": 0}
    retry_contexts: list[list] = []
    huge_result = "z" * (CHAR_BUDGET + 20_000)

    async def stream_round(client, model, tool_context, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield ("finish", ("", [{"id": "call_0", "name": "lookup", "arguments": "{}"}], "tool_calls"))
        elif calls["n"] in (2, 3):
            raise _bad_request_error()
            yield  # pragma: no cover
        else:
            retry_contexts.append(list(tool_context))
            yield ("finish", ("done", [], "stop"))

    with patch("backend.agent._stream_round", stream_round), \
         patch("backend.agent.execute_tool", AsyncMock(return_value=huge_result)), \
         patch("backend.agent._complete", AsyncMock(return_value="forced summary")):
        async for _ in _execute_with_fallback(channel, "fetch it"):
            pass

    assert calls["n"] == 4  # tool round, compact-only retry (still too big), truncated retry, success

    retry_context = retry_contexts[0]
    tool_messages = [m for m in retry_context if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "truncated" in tool_messages[0]["content"]
    assert len(tool_messages[0]["content"]) < len(huge_result)


async def test_context_length_exceeded_propagates_once_recovery_is_exhausted(channel):
    """If it's still too big after both recovery stages, that's a real bug (compaction/
    truncation not actually shrinking things) — it must surface loudly, not loop."""
    async def always_fails(*args, **kwargs):
        raise _bad_request_error()
        yield  # pragma: no cover

    with patch("backend.agent._stream_round", always_fails), \
         patch("backend.agent._complete", AsyncMock(return_value="forced summary")):
        with pytest.raises(BadRequestError):
            async for _ in _execute_with_fallback(channel, "hi"):
                pass


# --- budgeted rendering for the summarization prompt ---

def test_budget_unsummarized_lines_leaves_small_backlog_untouched():
    unsummarized = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert _budget_unsummarized_lines(unsummarized) == "USER: hi\nASSISTANT: hello"


CHAR_BUDGET = SUMMARIZE_TOKEN_BUDGET * CHARS_PER_TOKEN_ESTIMATE


def test_budget_unsummarized_lines_truncates_single_oversized_message():
    original = "y" * (CHAR_BUDGET + 5000)
    unsummarized = [{"role": "tool_result", "content": original}]
    result = _budget_unsummarized_lines(unsummarized)
    assert "truncated" in result
    assert len(result) < len(original)


def test_budget_unsummarized_lines_truncates_oldest_first_and_keeps_newest_intact():
    old = {"role": "tool_result", "content": "z" * CHAR_BUDGET}
    newest_user = {"role": "user", "content": "the actual new message"}
    result = _budget_unsummarized_lines([old, newest_user])
    # the newest message must survive fully intact
    assert result.endswith("USER: the actual new message")
    # the oversized old message got truncated, not fully dropped
    assert "truncated" in result
    assert "TOOL_RESULT:" in result


def test_budget_unsummarized_lines_truncates_progressively_across_multiple_old_messages():
    # Each old message alone is smaller than the total excess, so truncating just
    # the oldest down to the floor isn't enough — the next-oldest must also give
    # some ground, while the newest stays fully intact.
    old1 = {"role": "tool_result", "content": "a" * CHAR_BUDGET}
    old2 = {"role": "tool_result", "content": "b" * CHAR_BUDGET}
    newest = {"role": "user", "content": "brand new message"}
    result = _budget_unsummarized_lines([old1, old2, newest])

    assert result.endswith("USER: brand new message")
    lines = result.split("\n")
    assert "truncated" in lines[0]
    assert "truncated" in lines[1]
    # nothing fully removed — some of each old message's original char survives
    assert "a" in lines[0]
    assert "b" in lines[1]


async def test_compact_survives_a_single_oversized_message(channel):
    """A single huge tool result (bigger than the hard prompt ceiling on its own)
    must not stop compaction from succeeding — see boynton-bot.log incident where
    one 32k-char tool_result made every subsequent compact attempt fail forever."""
    await _persist_op(channel, {"op": "user_msg", "content": "fetch that page", "hidden": False})
    huge_tool_result = "y" * (CHAR_BUDGET + 20_000)  # bigger than the summarization budget on its own
    await _persist_op(
        channel,
        {"op": "tool_result", "tool_name": "web_fetch", "content": huge_tool_result, "hidden": False},
    )

    captured_prompt = {}

    async def capture_complete(client, model, messages):
        captured_prompt["content"] = messages[0]["content"]
        return "summary of the fetch"

    with patch("backend.agent._complete", capture_complete):
        assert await _compact(channel) is True

    assert len(captured_prompt["content"]) < len(huge_tool_result)
    assert "truncated" in captured_prompt["content"]


# --- _do_summarize: retry with a tighter budget on an actual context_length_exceeded ---

async def test_do_summarize_shrinks_budget_by_real_overage_on_retry(channel):
    unsummarized = [{"role": "user", "content": "z" * 200_000}]
    calls = {"n": 0}
    seen_lines: list[str] = []

    async def fake_complete(client, model, messages):
        calls["n"] += 1
        seen_lines.append(messages[0]["content"])
        if calls["n"] == 1:
            raise _bad_request_error()
        return "summary text"

    session = {"summary": None}
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            with patch("backend.agent._complete", fake_complete):
                result = await _do_summarize(conn, cur, None, "model", channel, session, unsummarized)

    assert calls["n"] == 2
    assert result["summary"] == "summary text"
    # the retry's budget was cut by the real reported overage, not a blind guess —
    # the retried prompt should come out visibly smaller than the first attempt's.
    assert len(seen_lines[1]) < len(seen_lines[0])


async def test_do_summarize_never_truncates_the_prior_summary(channel):
    """The old summary is already-compressed running memory, not raw backlog — a
    retry must shrink the unsummarized lines, never touch prior in full."""
    huge_prior = "p" * 200_000
    session = {"summary": huge_prior}
    unsummarized = [{"role": "user", "content": "hi"}]
    calls = {"n": 0}
    seen_messages: list[str] = []

    async def fake_complete(client, model, messages):
        calls["n"] += 1
        seen_messages.append(messages[0]["content"])
        if calls["n"] == 1:
            raise _bad_request_error()
        return "summary text"

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            with patch("backend.agent._complete", fake_complete):
                await _do_summarize(conn, cur, None, "model", channel, session, unsummarized)

    assert calls["n"] == 2
    for content in seen_messages:
        assert huge_prior in content


async def test_do_summarize_propagates_once_retries_are_exhausted(channel):
    session = {"summary": None}
    unsummarized = [{"role": "user", "content": "hi"}]

    async def always_fails(client, model, messages):
        raise _bad_request_error()

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            with patch("backend.agent._complete", always_fails):
                with pytest.raises(BadRequestError):
                    await _do_summarize(conn, cur, None, "model", channel, session, unsummarized)
