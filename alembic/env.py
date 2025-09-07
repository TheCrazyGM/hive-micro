from __future__ import annotations
import os
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy import create_engine
from alembic import context

# Ensure project root is on sys.path so 'app' package can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Disable watcher during migrations by default
os.environ.setdefault("HIVE_DISABLE_WATCHER", "1")

# Import Flask app and SQLAlchemy models to get metadata
from app import create_app  # noqa: E402
from app.models import db  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

app = create_app()

target_metadata = db.metadata

# set the database URL from env or app config
DB_URL = os.environ.get("DATABASE_URL") or app.config.get("SQLALCHEMY_DATABASE_URI")


def run_migrations_offline() -> None:
    url = DB_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DB_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
