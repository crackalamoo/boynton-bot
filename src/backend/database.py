import os

from psycopg_pool import ConnectionPool

DB_URL = os.getenv("DATABASE_URL", "postgresql:///boynton_bot")

pool = ConnectionPool(DB_URL, open=True)
