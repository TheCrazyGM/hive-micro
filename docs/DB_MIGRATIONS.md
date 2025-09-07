# Database Migrations

This project uses Alembic for schema migrations. This guide covers both production (PostgreSQL) and local development (SQLite).

## Requirements

- Install dependencies:

```bash
pip install -r requirements.txt
```

- Environment variables you may need:

- `DATABASE_URL` (recommended):
  - PostgreSQL: `postgresql+psycopg2://USER:PASS@HOST:PORT/DBNAME`
  - SQLite (local): `sqlite:///app.db`
- `HIVE_DISABLE_WATCHER` (optional): set to `1` during migrations to ensure the block watcher does not start.

## Fresh Production Setup (PostgreSQL)

1. Set environment variables:

```bash
export DATABASE_URL='postgresql+psycopg2://USER:PASS@HOST:PORT/DBNAME'
export HIVE_DISABLE_WATCHER=1
```

2. Apply all migrations:

```bash
alembic upgrade head
```

3. (Optional) Re-enable watcher after migrating:

```bash
unset HIVE_DISABLE_WATCHER
```

## Existing Production DB (Missing Columns)

If your DB already has most tables but is missing columns like `appreciations.topic_id` and `post_id`:

1. Set environment variables:

```bash
export DATABASE_URL='postgresql+psycopg2://USER:PASS@HOST:PORT/DBNAME'
export HIVE_DISABLE_WATCHER=1
```

2. Stamp to baseline and upgrade incrementally:

```bash
alembic stamp 0001_baseline
alembic upgrade 0002_add_appreciations_columns
```

3. (Optional) Re-enable watcher after migrating:

```bash
unset HIVE_DISABLE_WATCHER
```

## Local Development (SQLite)

Option A (recommended for parity with prod):

```bash
export DATABASE_URL='sqlite:///app.db'
export HIVE_DISABLE_WATCHER=1
alembic upgrade head
```

Option B (quick start): run the app and let it create tables.

- The app calls `db.create_all()` at startup and includes a lightweight SQLite-only shim that adds `appreciations.topic_id` and `post_id` if missing.
- For consistency with production, prefer running Alembic.

## Everyday Alembic Usage

- Create a new migration from model changes:

```bash
alembic revision -m "describe change" --autogenerate
```

- Apply latest migrations:

```bash
alembic upgrade head
```

- Roll back one migration:

```bash
alembic downgrade -1
```

- Show current DB revision:

```bash
alembic current
```

- Show migration history:

```bash
alembic history
```

## Notes

- The block watcher is gated by `HIVE_DISABLE_WATCHER`. Set it to `1` during migrations to avoid starting the background thread.
- The initial migration `0001_baseline` creates all core tables:
  - `checkpoints`, `messages`, `mention_state`, `moderation`, `moderation_actions`
  - Forum: `categories`, `topics`, `posts`, `topic_actions`
  - Hearts: `appreciations` (with `topic_id`, `post_id`, unique `(trx_id, username)`)
- Migration `0002_add_appreciations_columns` adds the `appreciations` columns if missing and attempts to add foreign keys when possible.
