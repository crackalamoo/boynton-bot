import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent import _build_tool_replay, _persist_op, _run_with_fallback


@pytest.fixture
async def channel():
    ch = "test_correction_tool_safety"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


def _sse_events_of_type(events: list[str], type_: str) -> list[dict]:
    parsed = [json.loads(e[len("data: "):]) for e in events]
    return [e for e in parsed if e.get("type") == type_]


# --- _build_tool_replay ---

def test_build_tool_replay_maps_call_to_result():
    messages = [
        {"role": "user", "content": "look something up"},
        {
            "role": "assistant", "content": "",
            "tool_calls": [{
                "id": "call_0", "type": "function",
                "function": {"name": "web_fetch", "arguments": '{"url": "https://example.com"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_0", "content": "page content"},
        {"role": "assistant", "content": "done"},
    ]
    replay = _build_tool_replay(messages)
    assert replay[("web_fetch", '{"url": "https://example.com"}')] == "page content"


def test_build_tool_replay_ignores_a_call_with_no_matching_tool_result():
    messages = [
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "call_0", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
        },
    ]
    assert _build_tool_replay(messages) == {}


# --- mid-loop enforcement ---

async def test_matching_tool_call_replays_recorded_result_without_executing(channel):
    calls = {"n": 0}

    async def stream_round(client, model, tool_context, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield ("finish", ("", [
                {"id": "call_0", "name": "web_fetch", "arguments": '{"url": "https://example.com"}'}
            ], "tool_calls"))
        else:
            yield ("finish", ("done", [], "stop"))

    tool_replay = {("web_fetch", '{"url": "https://example.com"}'): "original page content"}
    context = [{"role": "user", "content": "check that page again"}]

    with patch("backend.agent._stream_round", stream_round), \
         patch("backend.agent.execute_tool", new_callable=AsyncMock) as mock_execute:
        events = []
        async for sse in _run_with_fallback(channel, context, 0, tool_replay=tool_replay):
            events.append(sse)

    mock_execute.assert_not_called()
    tool_results = _sse_events_of_type(events, "tool_result")
    assert tool_results[0]["content"] == "original page content"


async def test_non_matching_side_effecting_call_is_stubbed_when_disallowed(channel, monkeypatch):
    monkeypatch.setenv("BOYNTON_EMAIL_RECIPIENT", "someone@example.com")
    calls = {"n": 0}

    async def stream_round(client, model, tool_context, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield ("finish", ("", [
                {"id": "call_0", "name": "send_email", "arguments": '{"subject": "hi", "body": "<p>hi</p>"}'}
            ], "tool_calls"))
        else:
            yield ("finish", ("done", [], "stop"))

    context = [{"role": "user", "content": "email someone"}]

    with patch("backend.agent._stream_round", stream_round):
        events = []
        async for sse in _run_with_fallback(channel, context, 0, allow_side_effects=False):
            events.append(sse)

    tool_results = _sse_events_of_type(events, "tool_result")
    # matches execute_email_tool_stub's shape, not a real send (which would fail with a
    # KeyError on the missing SMTP env vars and surface as "Invalid tool call: ...")
    assert tool_results[0]["content"] == "Email sent to someone@example.com: 'hi'"


async def test_side_effecting_call_runs_for_real_when_allowed(channel):
    calls = {"n": 0}

    async def stream_round(client, model, tool_context, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield ("finish", ("", [
                {"id": "call_0", "name": "send_email", "arguments": '{"subject": "hi", "body": "<p>hi</p>"}'}
            ], "tool_calls"))
        else:
            yield ("finish", ("done", [], "stop"))

    context = [{"role": "user", "content": "email someone"}]

    with patch("backend.agent._stream_round", stream_round), \
         patch("backend.agent.execute_tool", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = "Email sent to real@example.com: 'hi'"
        events = []
        async for sse in _run_with_fallback(channel, context, 0):
            events.append(sse)

    mock_execute.assert_called_once()
    tool_results = _sse_events_of_type(events, "tool_result")
    assert tool_results[0]["content"] == "Email sent to real@example.com: 'hi'"
