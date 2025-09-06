from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False)
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)
    type = db.Column(db.String(16), nullable=False, default="post")
    content = db.Column(db.Text, nullable=False)
    mentions = db.Column(db.Text, nullable=True)  # JSON string
    tags = db.Column(db.Text, nullable=True)  # JSON string
    reply_to = db.Column(db.String(64), nullable=True)
    raw_json = db.Column(db.Text, nullable=True)


class Checkpoint(db.Model):
    __tablename__ = "checkpoints"
    id = db.Column(db.Integer, primary_key=True)
    last_block = db.Column(db.Integer, nullable=False, default=0)


class MentionState(db.Model):
    __tablename__ = "mention_state"
    username = db.Column(db.String(32), primary_key=True)
    last_seen = db.Column(db.DateTime, nullable=True, index=True)


class Moderation(db.Model):
    __tablename__ = "moderation"
    # One row per moderated trx_id
    trx_id = db.Column(db.String(64), primary_key=True)
    visibility = db.Column(
        db.String(16), nullable=False, default="public"
    )  # public|hidden
    mod_by = db.Column(db.String(32), nullable=True)
    mod_reason = db.Column(db.Text, nullable=True)
    mod_at = db.Column(db.DateTime, nullable=True, index=True)


class ModerationAction(db.Model):
    __tablename__ = "moderation_actions"
    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), index=True, nullable=False)
    moderator = db.Column(db.String(32), index=True, nullable=False)
    action = db.Column(db.String(16), nullable=False)  # hide|unhide
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True)
    # Optional signature audit
    sig_message = db.Column(db.Text, nullable=True)
    sig_pubkey = db.Column(db.String(64), nullable=True)
    sig_value = db.Column(db.Text, nullable=True)


class Appreciation(db.Model):
    __tablename__ = "appreciations"
    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), index=True, nullable=False)
    username = db.Column(db.String(32), index=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, index=True)

    # Forum extensions - exactly one should be non-null
    topic_id = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("trx_id", "username", name="uq_appreciation_trx_user"),
    )


# ==================== FORUM MODELS ====================


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(32), nullable=False)
    is_active = db.Column(db.Boolean, default=True, index=True)

    # Relationship
    topics = db.relationship("Topic", backref="category", lazy="dynamic")


class Topic(db.Model):
    __tablename__ = "topics"

    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)

    # Content
    title = db.Column(db.String(200), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)

    # Organization
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    tags = db.Column(db.Text, nullable=True)  # JSON array
    mentions = db.Column(db.Text, nullable=True)  # JSON array

    # Topic state
    is_locked = db.Column(db.Boolean, default=False, index=True)
    is_pinned = db.Column(db.Boolean, default=False, index=True)
    is_hidden = db.Column(db.Boolean, default=False, index=True)

    # Cached statistics
    reply_count = db.Column(db.Integer, default=0)
    last_activity = db.Column(db.DateTime, nullable=True, index=True)
    last_author = db.Column(db.String(32), nullable=True)

    # Blockchain data
    raw_json = db.Column(db.Text, nullable=True)

    # Relationships
    posts = db.relationship("Post", backref="topic", lazy="dynamic")
    actions = db.relationship("TopicAction", backref="topic", lazy="dynamic")


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)

    # Content
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)

    # Relationships
    topic_id = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=True)

    # Metadata
    mentions = db.Column(db.Text, nullable=True)  # JSON array
    is_hidden = db.Column(db.Boolean, default=False, index=True)
    raw_json = db.Column(db.Text, nullable=True)

    # Self-referential relationship for direct replies
    replies = db.relationship(
        "Post", backref=db.backref("reply_to", remote_side=[id]), lazy="dynamic"
    )


class TopicAction(db.Model):
    __tablename__ = "topic_actions"

    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=False)
    moderator = db.Column(db.String(32), index=True, nullable=False)
    action = db.Column(db.String(16), nullable=False)  # lock, unlock, pin, unpin, move
    reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    # Action-specific data (JSON)
    action_data = db.Column(db.Text, nullable=True)
