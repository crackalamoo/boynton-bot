import pytest
from unittest.mock import AsyncMock, patch
from psycopg.rows import dict_row

import backend.agent as agent_module
from backend.agent import Agent, PRIMARY_MODEL, _persist_op, build_training_example
from backend.database import pool


async def _drain_background_tasks():
    for task in list(agent_module._background_tasks):
        await task


@pytest.fixture
async def channel():
    ch = "test_training"
    await _persist_op(ch, {"op": "ensure_session", "channel": ch})
    return ch


@pytest.fixture
def agent():
    return Agent()


# --- build_training_example ---

async def test_build_training_example_simple_turn(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})

    example = await build_training_example(reply_id)

    assert example["prompt"][-1] == {"role": "user", "content": "hello"}
    assert example["response"] == [{"role": "assistant", "content": "hi there"}]


async def test_build_training_example_rejects_intermediate_assistant_row(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "run ls", "hidden": False})
    intermediate_id = await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "file.txt"})
    await _persist_op(channel, {"op": "assistant_msg", "content": "Done", "hidden": False, "model": PRIMARY_MODEL})

    with pytest.raises(ValueError):
        await build_training_example(intermediate_id)


async def test_build_training_example_includes_tool_turn_in_response(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "run ls", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "file.txt"})
    final_id = await _persist_op(channel, {"op": "assistant_msg", "content": "Done", "hidden": False, "model": PRIMARY_MODEL})

    example = await build_training_example(final_id)
    response = example["response"]

    assert response[0]["role"] == "assistant"
    assert response[0]["tool_calls"][0]["function"]["name"] == "bash"
    assert response[1]["role"] == "tool"
    assert response[1]["content"] == "file.txt"
    assert response[2] == {"role": "assistant", "content": "Done"}


async def test_build_training_example_no_duplicate_tool_call_ids_across_prompt_and_response(channel):
    # A prior turn (in the prompt) with a tool call...
    await _persist_op(channel, {"op": "user_msg", "content": "first", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "a.txt"})
    await _persist_op(channel, {"op": "assistant_msg", "content": "first done", "hidden": False, "model": PRIMARY_MODEL})

    # ...and the judged turn (in the response) also with a tool call.
    await _persist_op(channel, {"op": "user_msg", "content": "second", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "pwd"}, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "/home"})
    final_id = await _persist_op(channel, {"op": "assistant_msg", "content": "second done", "hidden": False, "model": PRIMARY_MODEL})

    example = await build_training_example(final_id)
    combined = example["prompt"] + example["response"]

    tool_call_ids = [
        tc["id"] for m in combined if m.get("tool_calls") for tc in m["tool_calls"]
    ]
    assert len(tool_call_ids) == len(set(tool_call_ids)), f"duplicate tool_call ids: {tool_call_ids}"


async def test_build_training_example_rejects_non_primary_model_message(channel):
    # Derived from PRIMARY_MODEL, not a literal, so this stays different regardless of env
    # (PRIMARY_MODEL can be None if no localhost endpoint is configured).
    fallback_model = f"{PRIMARY_MODEL}-fallback"
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(
        channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": fallback_model}
    )

    with pytest.raises(ValueError):
        await build_training_example(reply_id)


async def test_build_training_example_rejects_message_with_no_model(channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False})

    with pytest.raises(ValueError):
        await build_training_example(reply_id)


# --- Agent.record_feedback / resolve_feedback ---

async def test_record_feedback_up(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})

    row = await agent.record_feedback(reply_id, "up")

    assert row["label"] == "up"
    assert row["correction_status"] is None
    assert row["correction"] is None
    assert row["response"] == [{"role": "assistant", "content": "hi there"}]


async def test_record_feedback_down_sets_pending(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})

    row = await agent.record_feedback(reply_id, "down")

    assert row["label"] == "down"
    assert row["correction_status"] == "pending"


async def test_record_feedback_twice_overwrites_row(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})

    first = await agent.record_feedback(reply_id, "down")
    second = await agent.record_feedback(reply_id, "up")

    assert first["id"] == second["id"]
    assert second["label"] == "up"
    assert second["correction_status"] is None


async def test_record_feedback_rejects_non_primary_model(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(
        channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": "some-other-hosted-model"}
    )

    with pytest.raises(ValueError):
        await agent.record_feedback(reply_id, "up")


async def test_resolve_feedback_approve_and_reject(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})
    row = await agent.record_feedback(reply_id, "down")

    approved = await agent.resolve_feedback(row["id"], "approve", correction=[{"role": "assistant", "content": "better"}])
    assert approved["correction_status"] == "approved"
    assert approved["correction"] == [{"role": "assistant", "content": "better"}]

    rejected = await agent.resolve_feedback(row["id"], "reject")
    assert rejected["correction_status"] == "rejected"


async def test_resolve_feedback_unknown_id_raises(agent):
    with pytest.raises(ValueError):
        await agent.resolve_feedback(999999, "approve")


# --- Agent.add_feedback_note / correction drafting ---

def _stream_rounds(*rounds):
    calls = iter(rounds)

    async def mock(*args, **kwargs):
        for event in next(calls):
            yield event

    return mock


async def test_add_feedback_note_requires_down_row(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "hello", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "hi there", "hidden": False, "model": PRIMARY_MODEL})
    row = await agent.record_feedback(reply_id, "up")

    with pytest.raises(ValueError):
        await agent.add_feedback_note(row["id"], "should have used a tool")


async def test_add_feedback_note_drafts_correction(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "what's the weather", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "it's sunny", "hidden": False, "model": PRIMARY_MODEL})
    row = await agent.record_feedback(reply_id, "down")

    mock = _stream_rounds(
        [("token", "Corrected answer"), ("finish", ("Corrected answer", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock):
        noted = await agent.add_feedback_note(row["id"], "should have checked a real source")
        assert noted["correction_status"] == "drafting"

        # Drafting runs as a background asyncio task; wait for it to finish
        # while the patch is still in effect.
        await _drain_background_tasks()

    final = await agent.get_feedback(row["id"])
    assert final["correction_status"] == "drafted"
    assert final["correction"] == [{"role": "assistant", "content": "Corrected answer"}]


async def test_add_feedback_note_marks_error_on_failure(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "what's the weather", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "it's sunny", "hidden": False, "model": PRIMARY_MODEL})
    row = await agent.record_feedback(reply_id, "down")

    async def broken_stream(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover - unreachable, makes this an async generator

    with patch("backend.agent._stream_round", broken_stream):
        await agent.add_feedback_note(row["id"], "bad note")
        await _drain_background_tasks()

    final = await agent.get_feedback(row["id"])
    assert final["correction_status"] == "error"


async def test_draft_correction_persists_to_isolated_channel(agent, channel):
    await _persist_op(channel, {"op": "user_msg", "content": "what's the weather", "hidden": False})
    reply_id = await _persist_op(channel, {"op": "assistant_msg", "content": "it's sunny", "hidden": False, "model": PRIMARY_MODEL})
    row = await agent.record_feedback(reply_id, "down")

    mock = _stream_rounds(
        [("token", "Corrected"), ("finish", ("Corrected", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock):
        await agent.add_feedback_note(row["id"], "check the note")
        await _drain_background_tasks()

    isolated_channel = f"training-correction-{row['id']}"
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT role FROM messages WHERE session_id = %s ORDER BY id", (isolated_channel,))
            rows = await cur.fetchall()

    assert [r["role"] for r in rows] == ["user", "assistant"]

    # The original 'web'-ish channel used for the turn must be untouched.
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM messages WHERE session_id = %s", (channel,))
            count_row = await cur.fetchone()
    assert count_row["n"] == 2


async def test_draft_correction_tool_call_ids_do_not_collide_with_prompt(agent, channel):
    # Prompt (a prior turn) contains a tool call...
    await _persist_op(channel, {"op": "user_msg", "content": "first", "hidden": False})
    await _persist_op(channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}, "model": PRIMARY_MODEL})
    await _persist_op(channel, {"op": "tool_result", "tool_name": "bash", "content": "a.txt"})
    await _persist_op(channel, {"op": "assistant_msg", "content": "first done", "hidden": False, "model": PRIMARY_MODEL})

    # ...the judged (bad) turn does not call a tool, which is exactly the failure mode
    # this feature exists to correct.
    await _persist_op(channel, {"op": "user_msg", "content": "what's on hn", "hidden": False})
    reply_id = await _persist_op(
        channel, {"op": "assistant_msg", "content": "I checked, nothing notable", "hidden": False, "model": PRIMARY_MODEL}
    )
    row = await agent.record_feedback(reply_id, "down")

    # The correction the agent drafts calls a tool for real this time.
    mock = _stream_rounds(
        [("finish", ("", [{"id": "call_x", "name": "bash", "arguments": '{"command": "curl hn"}'}], "tool_calls"))],
        [("finish", ("Top story: ...", [], "stop"))],
    )
    with patch("backend.agent._stream_round", mock), \
         patch("backend.agent.execute_tool", AsyncMock(return_value="Top story: ...")):
        await agent.add_feedback_note(row["id"], "you didn't actually check")
        await _drain_background_tasks()

    final = await agent.get_feedback(row["id"])
    assert final["correction_status"] == "drafted"

    combined = final["prompt"] + final["correction"]
    tool_call_ids = [tc["id"] for m in combined if m.get("tool_calls") for tc in m["tool_calls"]]
    assert len(tool_call_ids) == len(set(tool_call_ids)), f"duplicate tool_call ids: {tool_call_ids}"


# --- model persistence / eligibility signaling ---

async def test_persist_op_stores_model_on_assistant_and_tool_call_rows(channel):
    assistant_id = await _persist_op(
        channel, {"op": "assistant_msg", "content": "", "hidden": False, "model": PRIMARY_MODEL}
    )
    tool_call_id = await _persist_op(
        channel, {"op": "tool_call", "tool_name": "bash", "arguments": {"command": "ls"}, "model": PRIMARY_MODEL}
    )
    tool_result_id = await _persist_op(
        channel, {"op": "tool_result", "tool_name": "bash", "content": "file.txt"}
    )
    user_id = await _persist_op(channel, {"op": "user_msg", "content": "hi", "hidden": False})

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, model FROM messages WHERE id = ANY(%s)",
                ([assistant_id, tool_call_id, tool_result_id, user_id],),
            )
            rows = {r["id"]: r["model"] for r in await cur.fetchall()}

    assert rows[assistant_id] == PRIMARY_MODEL
    assert rows[tool_call_id] == PRIMARY_MODEL
    assert rows[tool_result_id] is None
    assert rows[user_id] is None


async def test_get_history_reports_is_primary_model_per_row(agent, channel):
    # PRIMARY_MODEL depends on ambient env (can even be None with no local endpoint
    # configured) — patch it to a known value so this test is deterministic.
    with patch.object(agent_module, "PRIMARY_MODEL", "the-local-model"):
        await _persist_op(channel, {"op": "user_msg", "content": "hi", "hidden": False})
        await _persist_op(channel, {"op": "assistant_msg", "content": "from local", "hidden": False, "model": "the-local-model"})
        await _persist_op(channel, {"op": "assistant_msg", "content": "from fallback", "hidden": False, "model": "some-other-model"})
        await _persist_op(channel, {"op": "assistant_msg", "content": "pre-migration row", "hidden": False})

        history = await agent.get_history(channel)
        by_content = {m["content"]: m for m in history["messages"] if m["role"] == "assistant"}

        assert by_content["from local"]["is_primary_model"] is True
        assert by_content["from fallback"]["is_primary_model"] is False
        assert by_content["pre-migration row"]["is_primary_model"] is False
