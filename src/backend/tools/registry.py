from .datetime_tool import DATETIME_TOOL, execute_datetime_tool

TOOLS = [DATETIME_TOOL]


def execute_tool(name: str, arguments: dict) -> str:
    if name == "get_current_datetime":
        return execute_datetime_tool()
    raise ValueError(f"Unknown tool: {name}")
