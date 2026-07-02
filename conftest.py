import os
import secrets
import shutil

# Must be set before any backend imports, which happen at collection time.
_BOYNTON_SUFFIX = secrets.token_hex(4)
_BOYNTON_TEST_DB = f"boynton_bot_test_{_BOYNTON_SUFFIX}"
_BOYNTON_TEST_DB_URL = f"postgresql:///{_BOYNTON_TEST_DB}"
_BOYNTON_TEST_MEMORY_DIR = f"/tmp/boynton_bot_test_memory_{_BOYNTON_SUFFIX}"

os.environ["BOYNTON_DATABASE_URL"] = _BOYNTON_TEST_DB_URL
os.environ["BOYNTON_MEMORY_DIR"] = _BOYNTON_TEST_MEMORY_DIR
os.environ.setdefault("BOYNTON_OPENAI_API_KEY", "test-not-real")

import pytest
import psycopg
from pathlib import Path

_BOYNTON_MIGRATIONS_DIR = Path(__file__).parent / "src" / "backend" / "db"
_BOYNTON_MIGRATION_FILES = [
    "0001_initial_schema.sql",
    "0002_add_tool_calls.sql",
    "0003_add_hidden_flag.sql",
    "0004_add_cron_jobs.sql",
    "0005_add_training_examples.sql",
    "0006_add_message_model.sql",
]


@pytest.fixture(scope="session", autouse=True)
def create_memory_dir():
    os.makedirs(_BOYNTON_TEST_MEMORY_DIR, exist_ok=True)
    yield
    shutil.rmtree(_BOYNTON_TEST_MEMORY_DIR, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def create_test_db():
    with psycopg.connect("postgresql:///postgres", autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {_BOYNTON_TEST_DB}")

    with psycopg.connect(_BOYNTON_TEST_DB_URL) as conn:
        for filename in _BOYNTON_MIGRATION_FILES:
            conn.execute((_BOYNTON_MIGRATIONS_DIR / filename).read_text())
        conn.commit()

    yield

    with psycopg.connect("postgresql:///postgres", autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {_BOYNTON_TEST_DB}")


@pytest.fixture(scope="session", autouse=True)
async def open_pool(create_test_db):
    import backend.database as db_module
    await db_module.pool.open()
    yield
    await db_module.pool.close()
