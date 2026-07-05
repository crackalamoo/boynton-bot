from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import backend.agent as agent_module
from backend.agent import Agent, NORMAL_MAX_PROMPT_TOKENS, _execute_with_fallback, _persist_op, _stream_round


async def _empty_stream():
    return
    yield  # pragma: no cover


def _make_client(mock_create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mock_create)))


async def _drain(gen):
    async for _ in gen:
        pass


async def test_stream_round_omits_priority_header_for_non_primary_model():
    with patch.object(agent_module, "PRIMARY_MODEL", "the-local-model"):
        mock_create = AsyncMock(return_value=_empty_stream())
        client = _make_client(mock_create)

        await _drain(_stream_round(client, "hosted-fallback-model", [{"role": "user", "content": "hi"}], priority="high"))

    kwargs = mock_create.call_args.kwargs
    assert "extra_headers" not in kwargs


async def test_stream_round_adds_high_priority_header_for_primary_model():
    with patch.object(agent_module, "PRIMARY_MODEL", "the-local-model"):
        mock_create = AsyncMock(return_value=_empty_stream())
        client = _make_client(mock_create)

        await _drain(_stream_round(client, "the-local-model", [{"role": "user", "content": "hi"}], priority="high"))

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_headers"] == {"X-Priority": "high", "X-Max-Prompt-Tokens": str(NORMAL_MAX_PROMPT_TOKENS)}


async def test_stream_round_adds_low_priority_header_for_primary_model():
    with patch.object(agent_module, "PRIMARY_MODEL", "the-local-model"):
        mock_create = AsyncMock(return_value=_empty_stream())
        client = _make_client(mock_create)

        await _drain(_stream_round(client, "the-local-model", [{"role": "user", "content": "hi"}], priority="low"))

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_headers"] == {"X-Priority": "low", "X-Max-Prompt-Tokens": str(NORMAL_MAX_PROMPT_TOKENS)}


# --- priority threading through the call chain ---

def _recording_stream_round(recorded):
    async def mock(*args, **kwargs):
        recorded.append(kwargs.get("priority"))
        yield ("finish", ("ok", [], "stop"))
    return mock


@pytest.fixture
async def channel():
    ch = "test_priority"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


@pytest.fixture
def agent():
    return Agent()


async def test_interactive_chat_defaults_to_high_priority(channel):
    recorded: list[str | None] = []
    with patch("backend.agent._stream_round", _recording_stream_round(recorded)):
        async for _ in _execute_with_fallback(channel, "hi"):
            pass

    assert recorded == ["high"]


async def test_draft_correction_uses_low_priority(agent, channel):
    from backend.agent import PRIMARY_MODEL

    await _persist_op(channel, {"op": "user_msg", "content": "what's the weather", "hidden": False})
    reply_id = await _persist_op(
        channel, {"op": "assistant_msg", "content": "it's sunny", "hidden": False, "model": PRIMARY_MODEL}
    )
    row = await agent.record_feedback(reply_id, "down")

    recorded: list[str | None] = []
    with patch("backend.agent._stream_round", _recording_stream_round(recorded)):
        await agent.add_feedback_note(row["id"], "check the note")
        for task in list(agent_module._background_tasks):
            await task

    assert recorded == ["low"]
