# Migrations

Migrations are plain SQL files numbered sequentially: `0001_initial_schema.sql`, `0002_...`, etc.

## Applying migrations

Run each file manually against your Postgres DB in order:

```sh
psql $BOYNTON_DATABASE_URL < src/backend/db/0005_your_migration.sql
```

There is no migration runner — apply them yourself and track which ones have run. Be careful to avoid re-applying migrations that have already been applied in a prior session.

## Adding a migration

1. Create a new file: next number in sequence, descriptive name
2. Write idempotent SQL where possible (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`)
3. Also add the filename to `_BOYNTON_MIGRATION_FILES` in `conftest.py` so the test suite applies it
