"""Add topic_id and post_id to appreciations if missing

Revision ID: 0002_add_appreciations_columns
Revises: 0001_baseline
Create Date: 2025-09-07
"""

from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0002_add_appreciations_columns"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "appreciations", "topic_id"):
        op.add_column(
            "appreciations", sa.Column("topic_id", sa.Integer(), nullable=True)
        )
    if not _has_column(bind, "appreciations", "post_id"):
        op.add_column(
            "appreciations", sa.Column("post_id", sa.Integer(), nullable=True)
        )
    # Optionally add FKs if target tables exist (safe no-op if they don't)
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "topics" in tables:
        # Add FK only if not already present
        # Alembic doesn't provide built-in 'if not exists' for constraints; skip if exists
        # relying on naming convention avoids duplicates, so we try-except
        try:
            op.create_foreign_key(
                "fk_appreciations_topic_id_topics",
                "appreciations",
                "topics",
                ["topic_id"],
                ["id"],
            )
        except Exception:
            pass
    if "posts" in tables:
        try:
            op.create_foreign_key(
                "fk_appreciations_post_id_posts",
                "appreciations",
                "posts",
                ["post_id"],
                ["id"],
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    # Drop FKs first (ignore if missing)
    try:
        op.drop_constraint(
            "fk_appreciations_topic_id_topics", "appreciations", type_="foreignkey"
        )
    except Exception:
        pass
    try:
        op.drop_constraint(
            "fk_appreciations_post_id_posts", "appreciations", type_="foreignkey"
        )
    except Exception:
        pass
    if _has_column(bind, "appreciations", "post_id"):
        op.drop_column("appreciations", "post_id")
    if _has_column(bind, "appreciations", "topic_id"):
        op.drop_column("appreciations", "topic_id")
