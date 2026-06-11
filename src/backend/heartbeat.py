import os
import threading
import time
import logging

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "600"))
HEARTBEAT_MAX_TOKENS = int(os.getenv("HEARTBEAT_MAX_TOKENS", "512"))
HEARTBEAT_ACK_MAX_CHARS = 300


def _load_heartbeat_instructions() -> str | None:
    """Returns HEARTBEAT.md content, or None if the file doesn't exist or is empty."""
    memory_dir = os.environ["MEMORY_DIR"]
    path = os.path.join(memory_dir, "HEARTBEAT.md")
    try:
        with open(path) as f:
            content = f.read()
        if not content.strip():
            return None
        return content
    except FileNotFoundError:
        return None


def _build_prompt(instructions: str) -> str:
    return (
        f"[Heartbeat check-in]\n\n{instructions}\n\n"
        f"If nothing requires your attention, reply with HEARTBEAT_OK. "
    )


def _is_suppressed(full_text: str) -> bool:
    """Return True if the response is a brief HEARTBEAT_OK acknowledgement."""
    if not full_text.startswith("HEARTBEAT_OK"):
        return False
    remainder = full_text[len("HEARTBEAT_OK"):].strip()
    return len(remainder) <= HEARTBEAT_ACK_MAX_CHARS


def _heartbeat_loop(agent, channel: str, interval_seconds: int):
    while True:
        time.sleep(interval_seconds)

        instructions = _load_heartbeat_instructions()
        if instructions is None:
            logger.info("Heartbeat skipped: HEARTBEAT.md not found or empty")
            continue

        try:
            logger.info(f"Heartbeat firing on channel {channel!r}")
            prompt = _build_prompt(instructions)
            agent.run_collect(channel, prompt, max_tokens=HEARTBEAT_MAX_TOKENS, is_suppressed=_is_suppressed)
        except Exception:
            logger.exception("Heartbeat error")


def start_heartbeat(agent) -> None:
    channel = os.getenv("HEARTBEAT_CHANNEL")
    if not channel:
        return
    interval_minutes = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30"))
    t = threading.Thread(
        target=_heartbeat_loop,
        args=(agent, channel, interval_minutes * 60),
        daemon=True,
    )
    t.start()
    logger.info(f"Heartbeat started: channel={channel!r}, interval={interval_minutes}m")
