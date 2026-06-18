import os

from psycopg_pool import AsyncConnectionPool

DB_URL = os.getenv("BOYNTON_DATABASE_URL", "postgresql:///boynton_bot")

pool = AsyncConnectionPool(DB_URL, open=False)
