"""
Sandboxed bash execution via Docker container.

Container lifecycle:
- Created fresh on first use or after the image changes
- Stopped after IDLE_TIMEOUT_SECS of inactivity
- Restarted automatically on next use
- home/ directory mounted at /home for persistent file storage
"""

import subprocess
import threading
import time
from pathlib import Path

DOCKER = "/usr/local/bin/docker"
CONTAINER_NAME = "boynton-sandbox"
IMAGE_NAME = "boynton-sandbox"
IDLE_TIMEOUT_SECS = 600  # 10 minutes
IDLE_CHECK_INTERVAL = 60  # check every 60s
MAX_OUTPUT_CHARS = 20_000
HEAD_LINES = 50
TAIL_LINES = 50

# Absolute path to docker/home on the host
_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # boynton-bot/
_HOME_DIR = _REPO_ROOT / "docker" / "home"

_lock = threading.Lock()
_last_used: float = 0.0
_idle_thread_started = False


def _run(cmd: list[str], check: bool = False, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        check=check,
    )


def _container_status() -> str:
    """Returns 'running', 'stopped', or 'missing'."""
    result = _run([DOCKER, "inspect", "--format", "{{.State.Status}}", CONTAINER_NAME])
    if result.returncode != 0:
        return "missing"
    status = result.stdout.strip()
    return "running" if status == "running" else "stopped"


def _build_image():
    dockerfile_dir = _REPO_ROOT / "docker"
    _ = _run([DOCKER, "build", "-t", IMAGE_NAME, str(dockerfile_dir)], check=True, capture=False)


def _start_container():
    _HOME_DIR.mkdir(parents=True, exist_ok=True)
    _ = _run([
        DOCKER, "run", "-d",
        "--name", CONTAINER_NAME,
        "-v", f"{_HOME_DIR.resolve()}:/home",
        "-w", "/home",
        "--network", "none",
        IMAGE_NAME,
        "sleep", "infinity",
    ], check=True)


def _ensure_running():
    """Ensure container is running, building/starting as needed."""
    global _last_used, _idle_thread_started
    status = _container_status()
    if status == "missing":
        _build_image()
        _start_container()
    elif status == "stopped":
        _ = _run([DOCKER, "start", CONTAINER_NAME], check=True)
    _last_used = time.monotonic()
    if not _idle_thread_started:
        _idle_thread_started = True
        t = threading.Thread(target=_idle_watcher, daemon=True)
        t.start()


def _idle_watcher():
    """Background thread: stop container after IDLE_TIMEOUT_SECS of inactivity."""
    while True:
        time.sleep(IDLE_CHECK_INTERVAL)
        with _lock:
            if _last_used > 0 and time.monotonic() - _last_used > IDLE_TIMEOUT_SECS:
                if _container_status() == "running":
                    _ = _run([DOCKER, "stop", CONTAINER_NAME])


def _truncate_output(output: str) -> str:
    """Truncate to HEAD_LINES + TAIL_LINES with omission notice, then cap at MAX_OUTPUT_CHARS."""
    lines = output.splitlines()
    if len(lines) > HEAD_LINES + TAIL_LINES:
        omitted = len(lines) - HEAD_LINES - TAIL_LINES
        lines = (
            lines[:HEAD_LINES]
            + [f"... ({omitted} lines omitted) ..."]
            + lines[-TAIL_LINES:]
        )
    result = "\n".join(lines)
    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS] + f"\n... (truncated at {MAX_OUTPUT_CHARS} chars) ..."
    return result


BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a bash command in a sandboxed Docker container. "
            "Working directory is /home. Network is disabled."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
}


def execute_bash(command: str, timeout: int = 60) -> str:
    """Run a shell command in the sandboxed Docker container."""
    with _lock:
        _ensure_running()

    try:
        result = subprocess.run(
            [DOCKER, "exec", CONTAINER_NAME, "sh", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # combine stderr into stdout
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[exit code {result.returncode}]"
    except subprocess.TimeoutExpired:
        # Kill the exec process; container keeps running
        _ = _run([DOCKER, "exec", CONTAINER_NAME, "sh", "-c", "kill -9 -1 2>/dev/null || true"])
        output = f"[command timed out after {timeout}s]"

    with _lock:
        _last_used = time.monotonic()

    return _truncate_output(output)

