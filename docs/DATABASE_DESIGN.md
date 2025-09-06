# Forum Database Design

## Overview

Database schema design for Hive Forum, building on the existing Hive Micro structure.

## New Models Required

### 1. Category

Forum categories/sections for organizing topics.

```python
class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)  # URL-friendly name
    name = db.Column(db.String(100), nullable=False)             # Display name
    description = db.Column(db.Text, nullable=True)             # Category description
    sort_order = db.Column(db.Integer, default=0)               # Display ordering
    created_at = db.Column(db.DateTime, nullable=False)
    created_by = db.Column(db.String(32), nullable=False)       # Admin who created
    is_active = db.Column(db.Boolean, default=True)             # Soft delete
```

### 2. Topic

Forum topics/threads (replaces Message for topic-level content).

```python
class Topic(db.Model):
    __tablename__ = "topics"

    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False)  # Blockchain tx
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)

    # Topic content
    title = db.Column(db.String(200), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)

    # Organization
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    tags = db.Column(db.Text, nullable=True)              # JSON array
    mentions = db.Column(db.Text, nullable=True)          # JSON array

    # Topic state
    is_locked = db.Column(db.Boolean, default=False)      # Can't reply when locked
    is_pinned = db.Column(db.Boolean, default=False)      # Sticky topics
    is_hidden = db.Column(db.Boolean, default=False)      # Moderation hiding

    # Cached statistics
    reply_count = db.Column(db.Integer, default=0)
    last_activity = db.Column(db.DateTime, nullable=True) # Last post timestamp
    last_author = db.Column(db.String(32), nullable=True) # Last post author

    raw_json = db.Column(db.Text, nullable=True)          # Original blockchain data
```

### 3. Post

Replies to topics (similar to current Message but topic-scoped).

```python
class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False)
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)

    # Post content
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)

    # Relationships
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)  # Direct reply

    # Metadata
    mentions = db.Column(db.Text, nullable=True)          # JSON array
    is_hidden = db.Column(db.Boolean, default=False)      # Moderation
    raw_json = db.Column(db.Text, nullable=True)
```

### 4. TopicAction

Audit log for topic administrative actions.

```python
class TopicAction(db.Model):
    __tablename__ = "topic_actions"

    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=False)
    moderator = db.Column(db.String(32), nullable=False)
    action = db.Column(db.String(16), nullable=False)     # lock, unlock, pin, unpin, move
    reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False)

    # Action-specific data (JSON)
    action_data = db.Column(db.Text, nullable=True)       # e.g., old/new category for moves
```

## Modified Existing Models

### Appreciation (Extended)

Add support for both topics and posts.

```python
# Add new columns:
topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=True)
post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
# Note: exactly one of topic_id or post_id should be non-null
```

### Moderation (Extended)

Support both topics and posts.

```python
# Add new columns:
topic_id = db.Column(db.Integer, db.ForeignKey('topics.id'), nullable=True)
post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
# Note: exactly one of topic_id or post_id should be non-null
```

## Relationships

```
Category (1) → (many) Topic
Topic (1) → (many) Post
Post (1) → (many) Post [self-referential for direct replies]
Topic (1) → (many) Appreciation
Post (1) → (many) Appreciation
Topic (1) → (many) TopicAction
```

## Indexes for Performance

- `topics.category_id, topics.is_pinned DESC, topics.last_activity DESC` (category browse)
- `topics.author, topics.timestamp DESC` (user's topics)
- `posts.topic_id, posts.timestamp ASC` (topic replies chronological)
- `posts.author, posts.timestamp DESC` (user's posts)
- `categories.sort_order, categories.name` (category listing)

## Migration Strategy

1. Create new tables alongside existing ones
2. Preserve existing `messages` table for backward compatibility during development
3. Update application to use new models
4. Eventually drop unused tables after thorough testing

