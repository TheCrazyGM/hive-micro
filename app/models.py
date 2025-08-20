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
