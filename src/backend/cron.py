import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from croniter import croniter
from psycopg.rows import dict_row

from backend.agent import Agent
from backend.database import pool

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


def _is_due(job: dict[str, Any], now: datetime) -> bool:
    if job["schedule_type"] == "at":
        if job["last_run_at"] is not None:
            return False
        scheduled = datetime.fromisoformat(job["schedule_value"])
        if scheduled.tzinfo is None:
            scheduled = scheduled.astimezone()
        return now >= scheduled
    elif job["schedule_type"] == "cron":
        base = job["last_run_at"] or job["created_at"]
        return croniter(job["schedule_value"], base).get_next(datetime) <= now
    else:
        logger.error(f"Unknown schedule_type {job['schedule_type']!r} for cron job {job['id']}")
        return False


def _run_tick(agent: Agent) -> None:
    now = datetime.now(timezone.utc)
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM cron_jobs WHERE enabled")
            jobs = cur.fetchall()

            for job in jobs:
                if not _is_due(job, now):
                    continue

                logger.info(f"Cron job {job['id']} ({job['name']!r}) firing on channel {job['channel']!r}")
                agent.submit_background(job["channel"], job["prompt"])

                if job["schedule_type"] == "at":
                    cur.execute(
                        "UPDATE cron_jobs SET last_run_at = %s, enabled = FALSE WHERE id = %s",
                        (now, job["id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE cron_jobs SET last_run_at = %s WHERE id = %s",
                        (now, job["id"]),
                    )
                conn.commit()


def _cron_loop(agent: Agent) -> None:
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            _run_tick(agent)
        except Exception:
            logger.exception("Cron tick error")


def start_cron(agent: Agent) -> None:
    t = threading.Thread(target=_cron_loop, args=(agent,), daemon=True)
    t.start()
    logger.info("Cron scheduler started")
