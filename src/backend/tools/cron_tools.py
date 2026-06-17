from datetime import datetime

from croniter import croniter
from psycopg.rows import dict_row

from backend.database import pool

ADD_CRON_JOB_TOOL = {
    "type": "function",
    "function": {
        "name": "add_cron_job",
        "description": (
            "Schedule a job that will send a prompt to the agent at a future time or on a "
            "recurring schedule. The prompt is delivered as a new chat message on the given "
            "channel when the job fires."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "A short human-readable name for the job.",
                },
                "channel": {
                    "type": "string",
                    "description": "The chat channel/session the job posts into. 'web' is the main chat.",
                },
                "prompt": {
                    "type": "string",
                    "description": "The instruction sent to the agent when the job fires.",
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["at", "cron"],
                    "description": "'at' for a one-time run, 'cron' for a recurring schedule.",
                },
                "schedule_value": {
                    "type": "string",
                    "description": (
                        "For 'at': an ISO 8601 timestamp (e.g. '2026-06-15T09:00:00'). "
                        "For 'cron': a 5-field cron expression (e.g. '*/30 * * * *')."
                    ),
                },
            },
            "required": ["name", "channel", "prompt", "schedule_type", "schedule_value"],
        },
    },
}

LIST_CRON_JOBS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_cron_jobs",
        "description": "List all scheduled cron jobs.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

REMOVE_CRON_JOB_TOOL = {
    "type": "function",
    "function": {
        "name": "remove_cron_job",
        "description": "Delete a scheduled cron job by id.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "The id of the cron job to remove.",
                },
            },
            "required": ["id"],
        },
    },
}


def _parse_at(schedule_value: str) -> datetime:
    """Parse an 'at' schedule_value, treating naive timestamps as local time."""
    parsed = datetime.fromisoformat(schedule_value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


async def execute_add_cron_job(
    name: str,
    channel: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
) -> str:
    if schedule_type == "cron":
        try:
            croniter(schedule_value)
        except Exception as e:
            return f"Error: invalid cron expression {schedule_value!r}: {e}"
    elif schedule_type == "at":
        try:
            _parse_at(schedule_value)
        except ValueError as e:
            return f"Error: invalid timestamp {schedule_value!r}: {e}"
    else:
        return f"Error: invalid schedule_type {schedule_type!r}, must be 'at' or 'cron'"

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """INSERT INTO cron_jobs (name, channel, prompt, schedule_type, schedule_value)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (name, channel, prompt, schedule_type, schedule_value),
            )
            row = await cur.fetchone()
            await conn.commit()

    if row is None:
        return "Error: failed to create cron job"
    return f"Created cron job {row['id']}: {name!r} on channel {channel!r} ({schedule_type} {schedule_value!r})"


async def execute_list_cron_jobs() -> str:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM cron_jobs ORDER BY id ASC")
            jobs = await cur.fetchall()

    if not jobs:
        return "(no cron jobs)"

    lines = []
    for job in jobs:
        prompt = job["prompt"]
        if len(prompt) > 80:
            prompt = prompt[:77] + "..."
        lines.append(
            f"id={job['id']} name={job['name']!r} channel={job['channel']!r} "
            f"schedule={job['schedule_type']} {job['schedule_value']!r} "
            f"enabled={job['enabled']} last_run_at={job['last_run_at']} "
            f"prompt={prompt!r}"
        )
    return "\n".join(lines)


async def execute_remove_cron_job(id: int) -> str:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("DELETE FROM cron_jobs WHERE id = %s RETURNING id", (id,))
            row = await cur.fetchone()
            await conn.commit()

    if row is None:
        return f"Error: no cron job with id {id}"
    return f"Removed cron job {id}"
