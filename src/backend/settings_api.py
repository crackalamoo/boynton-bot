import os
import subprocess
import threading

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

# src/backend/settings_api.py -> repo root is two directories up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(ROOT, ".env")

SETTINGS_KEYS = [
    "BOYNTON_OPENAI_API_KEY",
    "BOYNTON_LLM_BASE_URL",
    "BOYNTON_LLM_MODEL",
    "BOYNTON_MEMORY_DIR",
    "BOYNTON_EMAIL_ADDRESS",
    "BOYNTON_EMAIL_PASSWORD",
    "BOYNTON_EMAIL_SMTP_HOST",
    "BOYNTON_EMAIL_SMTP_PORT",
    "BOYNTON_EMAIL_RECIPIENT",
]

SECRET_SETTINGS_KEYS = {"BOYNTON_OPENAI_API_KEY", "BOYNTON_EMAIL_PASSWORD"}

SECRET_PLACEHOLDER = "__SET__"


def _parse_env_file(path: str) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file, ignoring blank lines and comments."""
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


class SettingsRequest(BaseModel):
    BOYNTON_OPENAI_API_KEY: str | None = None
    BOYNTON_LLM_BASE_URL: str | None = None
    BOYNTON_LLM_MODEL: str | None = None
    BOYNTON_MEMORY_DIR: str | None = None
    BOYNTON_EMAIL_ADDRESS: str | None = None
    BOYNTON_EMAIL_PASSWORD: str | None = None
    BOYNTON_EMAIL_SMTP_HOST: str | None = None
    BOYNTON_EMAIL_SMTP_PORT: str | None = None
    BOYNTON_EMAIL_RECIPIENT: str | None = None


router = APIRouter()


@router.get("/api/settings")
async def get_settings():
    current = _parse_env_file(ENV_PATH)
    result = {}
    for key in SETTINGS_KEYS:
        value = current.get(key, "")
        if key in SECRET_SETTINGS_KEYS:
            result[key] = SECRET_PLACEHOLDER if value else ""
        else:
            result[key] = value
    return result


@router.post("/api/settings")
async def update_settings(body: SettingsRequest):
    current = _parse_env_file(ENV_PATH)
    submitted = body.model_dump()

    new_values: dict[str, str] = {}
    for key in SETTINGS_KEYS:
        value = submitted.get(key)
        if value is None:
            continue
        if key in SECRET_SETTINGS_KEYS:
            if value == SECRET_PLACEHOLDER or value == "":
                # Keep existing secret untouched.
                continue
            new_values[key] = value
        else:
            new_values[key] = value

    if not new_values:
        return {"ok": True}

    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()

    remaining = dict(new_values)
    updated_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                updated_lines.append(f"{key}={remaining.pop(key)}\n")
                continue
        updated_lines.append(line)

    # Append any new keys that weren't already present in the file.
    if remaining:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"
        for key, value in remaining.items():
            updated_lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(updated_lines)

    return {"ok": True}


@router.post("/api/restart")
async def restart(background_tasks: BackgroundTasks):
    def _do_restart():
        subprocess.run(
            ["sudo", "-n", "/bin/launchctl", "kickstart", "-k", "system/boynton-bot"],
            check=False,
        )

    def _schedule_restart():
        threading.Timer(0.5, _do_restart).start()

    background_tasks.add_task(_schedule_restart)
    return {"ok": True}
