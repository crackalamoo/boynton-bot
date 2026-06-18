import pytest
from backend.agent import _persist_op, _build_context


@pytest.fixture
async def channel():
    ch = "test_channel"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


async def test_build_context_appends_new_user_message(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False})

    context, _ = await _build_context(None, None, channel, "follow-up question")

    assert context[-1] == {"role": "user", "content": "follow-up question"}


async def test_tool_call_pairs_with_result(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "run ls", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "file.txt"})
    await _persist_op(channel, {"op": "assistant_msg", "content": "Done", "hidden": False})

    context, _ = await _build_context(None, None, channel, "next message")

    assistant = next(m for m in context if m["role"] == "assistant" and "tool_calls" in m)
    tool_result = next(m for m in context if m["role"] == "tool")

    assert assistant["tool_calls"][0]["function"]["name"] == "bash"
    assert tool_result["content"] == "file.txt"
    assert tool_result["tool_call_id"] == assistant["tool_calls"][0]["id"]


async def test_multiple_tool_calls_in_one_round_all_pair(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "do stuff", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "pwd"}})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "result_ls"})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "result_pwd"})
    await _persist_op(channel, {"op": "assistant_msg", "content": "Done", "hidden": False})

    context, _ = await _build_context(None, None, channel, "next")

    assistant = next(m for m in context if m["role"] == "assistant" and "tool_calls" in m)
    tool_results = [m for m in context if m["role"] == "tool"]

    assert len(assistant["tool_calls"]) == 2
    assert len(tool_results) == 2
    tc_ids = {tc["id"] for tc in assistant["tool_calls"]}
    for tr in tool_results:
        assert tr["tool_call_id"] in tc_ids
