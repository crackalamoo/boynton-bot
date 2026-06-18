import pytest
import backend.database as db_module


@pytest.fixture(autouse=True)
async def clean_tables():
    yield
    async with db_module.pool.connection() as conn:
        await conn.execute("TRUNCATE messages, sessions, cron_jobs RESTART IDENTITY CASCADE")
        await conn.commit()
