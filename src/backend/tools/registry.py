import asyncio
from typing import Any

from .bash_tool import BASH_TOOL, execute_bash, execute_bash_stub
from .cron_tools import (
    ADD_CRON_JOB_TOOL, LIST_CRON_JOBS_TOOL, REMOVE_CRON_JOB_TOOL,
    execute_add_cron_job, execute_add_cron_job_stub,
    execute_list_cron_jobs,
    execute_remove_cron_job, execute_remove_cron_job_stub,
)
from .datetime_tool import DATETIME_TOOL, execute_datetime_tool
from .email_tool import EMAIL_TOOL, execute_email_tool, execute_email_tool_stub
from .fetch_tool import WEB_FETCH_TOOL, execute_web_fetch
from .memory_tools import (
    LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL,
    execute_list_memory, execute_read_memory,
    execute_write_memory, execute_write_memory_stub,
)

TOOLS = [
    BASH_TOOL, DATETIME_TOOL, EMAIL_TOOL, WEB_FETCH_TOOL,
    LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL,
    ADD_CRON_JOB_TOOL, LIST_CRON_JOBS_TOOL, REMOVE_CRON_JOB_TOOL,
]

# Tools with real-world side effects. When a caller can't guarantee those effects are
# wanted (e.g. correction drafting, which re-runs tool calls against training data
# rather than a live user request), execute_tool(..., allow_side_effects=False) routes
# these to a stub in the same module that returns the same success shape without
# actually doing anything.
SIDE_EFFECTING_TOOLS = {"bash", "send_email", "write_memory", "add_cron_job", "remove_cron_job"}


async def execute_tool(name: str, arguments: dict[str, Any], allow_side_effects: bool = True) -> str:
    if not allow_side_effects and name in SIDE_EFFECTING_TOOLS:
        return await _execute_stub_tool(name, arguments)
    if name == "bash":
        return await asyncio.to_thread(execute_bash, arguments["command"], arguments.get("timeout", 60))
    if name == "get_current_datetime":
        return execute_datetime_tool()
    if name == "send_email":
        return await asyncio.to_thread(execute_email_tool, arguments["subject"], arguments["body"])
    if name == "web_fetch":
        return await asyncio.to_thread(execute_web_fetch, arguments["url"])
    if name == "list_memory":
        return await asyncio.to_thread(execute_list_memory, arguments.get("folder", ""))
    if name == "read_memory":
        return await asyncio.to_thread(execute_read_memory, arguments["path"])
    if name == "write_memory":
        return await asyncio.to_thread(execute_write_memory, arguments["path"], arguments["content"])
    if name == "add_cron_job":
        return await execute_add_cron_job(
            arguments["name"],
            arguments["channel"],
            arguments["prompt"],
            arguments["schedule_type"],
            arguments["schedule_value"],
        )
    if name == "list_cron_jobs":
        return await execute_list_cron_jobs()
    if name == "remove_cron_job":
        return await execute_remove_cron_job(arguments["id"])
    raise ValueError(f"Unknown tool: {name}")


async def _execute_stub_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "bash":
        return execute_bash_stub(arguments["command"])
    if name == "send_email":
        return execute_email_tool_stub(arguments["subject"], arguments["body"])
    if name == "write_memory":
        return await asyncio.to_thread(execute_write_memory_stub, arguments["path"], arguments["content"])
    if name == "add_cron_job":
        return execute_add_cron_job_stub(
            arguments["name"],
            arguments["channel"],
            arguments["prompt"],
            arguments["schedule_type"],
            arguments["schedule_value"],
        )
    if name == "remove_cron_job":
        return await execute_remove_cron_job_stub(arguments["id"])
    raise ValueError(f"Unknown stubbed tool: {name}")

