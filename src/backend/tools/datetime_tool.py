from datetime import datetime

DATETIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_datetime",
        "description": "Returns the current local date and time.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def execute_datetime_tool() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
