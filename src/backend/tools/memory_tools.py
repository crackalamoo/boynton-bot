import os
from datetime import datetime, timezone

MEMORY_DIR = None  # resolved at call time from env


def _get_memory_dir() -> str:
    return os.environ["BOYNTON_MEMORY_DIR"]


def _safe_resolve(rel_path: str) -> str:
    """Resolve rel_path under MEMORY_DIR and raise if it escapes."""
    memory_dir = os.path.realpath(_get_memory_dir())
    full = os.path.realpath(os.path.join(memory_dir, rel_path))
    if not full.startswith(memory_dir + os.sep) and full != memory_dir:
        raise ValueError(f"Path '{rel_path}' escapes memory directory")
    return full


LIST_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "list_memory",
        "description": "List files and subdirectories in the memory directory (or a subfolder of it).",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Subfolder path relative to memory root. Defaults to root if omitted.",
                },
            },
            "required": [],
        },
    },
}

READ_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "read_memory",
        "description": "Read a file from the memory directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to memory root.",
                },
            },
            "required": ["path"],
        },
    },
}

WRITE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "write_memory",
        "description": "Write content to a file in the memory directory, creating directories as needed. Pass empty content to delete the file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to memory root.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
}


def _build_tree(directory: str, prefix: str = "") -> list[str]:
    """Return a list of formatted lines for the directory tree."""
    try:
        entries = os.listdir(directory)
    except PermissionError:
        return [f"{prefix}<permission denied>"]

    dirs = sorted(e for e in entries if os.path.isdir(os.path.join(directory, e)))
    files = sorted(e for e in entries if os.path.isfile(os.path.join(directory, e)))

    lines = []
    for d in dirs:
        lines.append(f"{prefix}{d}/")
        lines.extend(_build_tree(os.path.join(directory, d), prefix + "  "))
    for f in files:
        lines.append(f"{prefix}{f}")
    return lines


def execute_list_memory(folder: str = "") -> str:
    memory_dir = _get_memory_dir()
    if folder:
        try:
            target = _safe_resolve(folder)
        except ValueError as e:
            return f"Error: {e}"
    else:
        target = os.path.realpath(memory_dir)

    if not os.path.isdir(target):
        return f"Error: folder '{folder}' does not exist"

    lines = _build_tree(target)
    if not lines:
        return "(empty)"
    return "\n".join(lines)


def execute_read_memory(path: str) -> str:
    try:
        full_path = _safe_resolve(path)
    except ValueError as e:
        return f"Error: {e}"

    if not os.path.isfile(full_path):
        return f"Error: file '{path}' does not exist"

    mtime = os.path.getmtime(full_path)
    last_updated_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    last_updated = last_updated_dt.strftime("%Y-%m-%d %H:%M UTC")
    age_days = (datetime.now(timezone.utc) - last_updated_dt).days

    with open(full_path, "r") as f:
        content = f.read()

    suffix = "\n[This file is over 30 days old — consider updating or deleting it.]" if age_days > 30 else ""
    return f"Last updated: {last_updated}\n{content}{suffix}"


def execute_write_memory(path: str, content: str) -> str:
    if os.path.normpath(path) == "SOUL.md":
        return "Error: SOUL.md is read-only"
    try:
        full_path = _safe_resolve(path)
    except ValueError as e:
        return f"Error: {e}"

    if not content.strip():
        if os.path.isfile(full_path):
            os.remove(full_path)
            return f"Deleted {path}"
        return f"Error: file '{path}' does not exist"

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content)

    return f"Written to {path}"


def execute_write_memory_stub(path: str, content: str) -> str:
    """Same validation and success message as execute_write_memory, without touching disk."""
    if os.path.normpath(path) == "SOUL.md":
        return "Error: SOUL.md is read-only"
    try:
        full_path = _safe_resolve(path)
    except ValueError as e:
        return f"Error: {e}"

    if not content.strip():
        if os.path.isfile(full_path):
            return f"Deleted {path}"
        return f"Error: file '{path}' does not exist"

    return f"Written to {path}"

