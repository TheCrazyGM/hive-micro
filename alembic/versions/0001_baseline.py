"""Initial schema creation

Revision ID: 0001_baseline
Revises:
Create Date: 2025-09-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # checkpoints
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_block", sa.Integer(), nullable=False, server_default="0"),
    )

    # messages (timeline)
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trx_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("block_num", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="post"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentions", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("reply_to", sa.String(length=64), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
    )

    # mention_state
    op.create_table(
        "mention_state",
        sa.Column("username", sa.String(length=32), primary_key=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
    )

    # moderation summary per trx_id
    op.create_table(
        "moderation",
        sa.Column("trx_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "visibility", sa.String(length=16), nullable=False, server_default="public"
        ),
        sa.Column("mod_by", sa.String(length=32), nullable=True),
        sa.Column("mod_reason", sa.Text(), nullable=True),
        sa.Column("mod_at", sa.DateTime(), nullable=True),
    )

    # moderation actions log
    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trx_id", sa.String(length=64), nullable=False),
        sa.Column("moderator", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sig_message", sa.Text(), nullable=True),
        sa.Column("sig_pubkey", sa.String(length=64), nullable=True),
        sa.Column("sig_value", sa.Text(), nullable=True),
    )

    # forum: categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=True, server_default=sa.text("1")
        ),
    )

    # forum: topics
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trx_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("block_num", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False
        ),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("mentions", sa.Text(), nullable=True),
        sa.Column(
            "is_locked", sa.Boolean(), nullable=True, server_default=sa.text("0")
        ),
        sa.Column(
            "is_pinned", sa.Boolean(), nullable=True, server_default=sa.text("0")
        ),
        sa.Column(
            "is_hidden", sa.Boolean(), nullable=True, server_default=sa.text("0")
        ),
        sa.Column("reply_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("last_activity", sa.DateTime(), nullable=True),
        sa.Column("last_author", sa.String(length=32), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
    )

    # forum: posts
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trx_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("block_num", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column(
            "reply_to_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=True
        ),
        sa.Column("mentions", sa.Text(), nullable=True),
        sa.Column(
            "is_hidden", sa.Boolean(), nullable=True, server_default=sa.text("0")
        ),
        sa.Column("raw_json", sa.Text(), nullable=True),
    )

    # forum: topic actions
    op.create_table(
        "topic_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("moderator", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("action_data", sa.Text(), nullable=True),
    )

    # appreciations (hearts)
    op.create_table(
        "appreciations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trx_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=True),
        sa.UniqueConstraint("trx_id", "username", name="uq_appreciation_trx_user"),
    )


def downgrade() -> None:
    op.drop_table("appreciations")
    op.drop_table("topic_actions")
    op.drop_table("posts")
    op.drop_table("topics")
    op.drop_table("categories")
    op.drop_table("moderation_actions")
    op.drop_table("moderation")
    op.drop_table("mention_state")
    op.drop_table("messages")
    op.drop_table("checkpoints")
