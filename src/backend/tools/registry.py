import asyncio
from typing import Any

from .bash_tool import BASH_TOOL, execute_bash
from .cron_tools import (
    ADD_CRON_JOB_TOOL, LIST_CRON_JOBS_TOOL, REMOVE_CRON_JOB_TOOL,
    execute_add_cron_job, execute_list_cron_jobs, execute_remove_cron_job,
)
from .datetime_tool import DATETIME_TOOL, execute_datetime_tool
from .email_tool import EMAIL_TOOL, execute_email_tool
from .fetch_tool import WEB_FETCH_TOOL, execute_web_fetch
from .memory_tools import (
    LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL,
    execute_list_memory, execute_read_memory, execute_write_memory,
)

TOOLS = [
    BASH_TOOL, DATETIME_TOOL, EMAIL_TOOL, WEB_FETCH_TOOL,
    LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL,
    ADD_CRON_JOB_TOOL, LIST_CRON_JOBS_TOOL, REMOVE_CRON_JOB_TOOL,
]


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
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

