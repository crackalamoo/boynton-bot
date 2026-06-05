from .datetime_tool import DATETIME_TOOL, execute_datetime_tool
from .fetch_tool import WEB_FETCH_TOOL, execute_web_fetch
from .memory_tools import (
    LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL,
    execute_list_memory, execute_read_memory, execute_write_memory,
)

TOOLS = [DATETIME_TOOL, WEB_FETCH_TOOL, LIST_MEMORY_TOOL, READ_MEMORY_TOOL, WRITE_MEMORY_TOOL]


def execute_tool(name: str, arguments: dict) -> str:
    if name == "get_current_datetime":
        return execute_datetime_tool()
    if name == "web_fetch":
        return execute_web_fetch(arguments["url"])
    if name == "list_memory":
        return execute_list_memory(arguments.get("folder", ""))
    if name == "read_memory":
        return execute_read_memory(arguments["path"])
    if name == "write_memory":
        return execute_write_memory(arguments["path"], arguments["content"])
    raise ValueError(f"Unknown tool: {name}")

