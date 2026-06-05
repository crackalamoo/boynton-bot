from .datetime_tool import DATETIME_TOOL, execute_datetime_tool
from .fetch_tool import WEB_FETCH_TOOL, execute_web_fetch

TOOLS = [DATETIME_TOOL, WEB_FETCH_TOOL]


def execute_tool(name: str, arguments: dict) -> str:
    if name == "get_current_datetime":
        return execute_datetime_tool()
    if name == "web_fetch":
        return execute_web_fetch(arguments["url"])
    raise ValueError(f"Unknown tool: {name}")
