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


class ModerationState(db.Model):
    __tablename__ = "moderation_state"
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

    __table_args__ = (
        db.UniqueConstraint("trx_id", "username", name="uq_appreciation_trx_user"),
    )
