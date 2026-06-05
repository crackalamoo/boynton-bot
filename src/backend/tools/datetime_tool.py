from datetime import datetime, timezone

DATETIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_datetime",
        "description": "Returns the current date and time in UTC.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def execute_datetime_tool() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
