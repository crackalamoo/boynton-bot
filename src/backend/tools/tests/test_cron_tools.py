from psycopg.rows import dict_row

from backend.database import pool
from backend.tools.cron_tools import execute_add_cron_job_stub, execute_remove_cron_job_stub


def test_add_cron_job_stub_still_validates_schedule():
    result = execute_add_cron_job_stub("test job", "web", "do something", "at", "not-a-timestamp")
    assert "Error" in result


async def test_add_cron_job_stub_returns_success_message_without_inserting():
    result = execute_add_cron_job_stub("test job", "web", "do something", "at", "2026-06-15T09:00:00")
    assert "Created cron job stub" in result

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM cron_jobs WHERE name = %s", ("test job",))
            assert await cur.fetchone() is None


async def test_remove_cron_job_stub_reports_success_without_deleting():
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """INSERT INTO cron_jobs (name, channel, prompt, schedule_type, schedule_value)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                ("stub target", "web", "do something", "at", "2026-06-15T09:00:00"),
            )
            row = await cur.fetchone()
            await conn.commit()
    job_id = row["id"]

    result = await execute_remove_cron_job_stub(job_id)
    assert result == f"Removed cron job {job_id}"

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id FROM cron_jobs WHERE id = %s", (job_id,))
            assert await cur.fetchone() is not None


async def test_remove_cron_job_stub_reports_error_for_missing_id():
    result = await execute_remove_cron_job_stub(999_999_999)
    assert "Error" in result
