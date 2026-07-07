from unittest.mock import patch

import pytest

from backend.tools.registry import SIDE_EFFECTING_TOOLS, execute_tool


async def test_allow_side_effects_false_routes_send_email_to_stub(monkeypatch):
    monkeypatch.setenv("BOYNTON_EMAIL_RECIPIENT", "someone@example.com")
    with patch("backend.tools.registry.execute_email_tool") as real_send:
        result = await execute_tool(
            "send_email", {"subject": "hi", "body": "<p>hi</p>"}, allow_side_effects=False
        )
    real_send.assert_not_called()
    assert result == "Email sent to someone@example.com: 'hi'"


async def test_allow_side_effects_true_still_calls_the_real_tool():
    with patch("backend.tools.registry.execute_email_tool", return_value="real result") as real_send:
        result = await execute_tool("send_email", {"subject": "hi", "body": "<p>hi</p>"})
    real_send.assert_called_once()
    assert result == "real result"


async def test_read_only_tools_ignore_allow_side_effects(tmp_path, monkeypatch):
    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    result = await execute_tool("list_memory", {}, allow_side_effects=False)
    assert result == "(empty)"


@pytest.mark.parametrize("name", sorted(SIDE_EFFECTING_TOOLS))
async def test_every_side_effecting_tool_has_a_stub_dispatch(name, tmp_path, monkeypatch):
    # Not exercising each one fully here (covered in their own tool test files) — just
    # confirming registry.py's stub dispatcher recognizes every declared side-effecting
    # tool, so adding one to SIDE_EFFECTING_TOOLS without a stub branch fails loudly.
    from backend.tools import registry

    monkeypatch.setenv("BOYNTON_MEMORY_DIR", str(tmp_path))
    monkeypatch.setenv("BOYNTON_EMAIL_RECIPIENT", "someone@example.com")

    stub_args = {
        "bash": {"command": "echo hi"},
        "send_email": {"subject": "s", "body": "b"},
        "write_memory": {"path": "x.md", "content": ""},
        "add_cron_job": {
            "name": "n", "channel": "web", "prompt": "p",
            "schedule_type": "at", "schedule_value": "not-a-real-timestamp",
        },
        "remove_cron_job": {"id": 999_999_999},
    }[name]
    result = await registry._execute_stub_tool(name, stub_args)
    assert isinstance(result, str)
