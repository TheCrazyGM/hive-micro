# Hive Forum Protocol Specification

## Overview

The Hive Forum protocol extends the Hive Micro architecture to support message board/forum functionality using Hive blockchain custom_json operations.

## Protocol Identification

- **APP_ID**: `hive.forum` (configurable via `HIVE_FORUM_APP_ID`)
- **Version**: `1` (protocol version)

## Operation Types

### 1. Topic Creation

Creates a new discussion topic/thread.

```json
{
  "app": "hive.forum",
  "v": 1,
  "type": "topic",
  "title": "Topic Title (max 200 chars)",
  "content": "Initial topic content/description",
  "category": "general",
  "tags": ["tag1", "tag2"],
  "mentions": ["@user1", "@user2"]
}
```

**Fields:**

- `title`: Required topic title (max 200 characters)
- `content`: Required initial post content
- `category`: Optional category slug (default: "general")
- `tags`: Optional array of topic tags
- `mentions`: Optional array of mentioned users

### 2. Topic Reply

Replies to an existing topic.

```json
{
  "app": "hive.forum",
  "v": 1,
  "type": "post",
  "content": "Reply content",
  "topic_id": "abc123...",
  "reply_to": "def456...",
  "mentions": ["@user1"]
}
```

**Fields:**

- `content`: Required reply content
- `topic_id`: Required transaction ID of the topic being replied to
- `reply_to`: Optional transaction ID for direct reply to another post
- `mentions`: Optional array of mentioned users

### 3. Topic Management (Moderator Only)

Administrative actions on topics.

```json
{
  "app": "hive.forum",
  "v": 1,
  "type": "topic_action",
  "action": "lock|unlock|pin|unpin|move",
  "topic_id": "abc123...",
  "reason": "Optional reason",
  "category": "new-category"
}
```

**Fields:**

- `action`: Required action type
- `topic_id`: Required target topic transaction ID
- `reason`: Optional reason for the action
- `category`: Required for "move" action, target category

### 4. Category Management (Admin Only)

Create or modify forum categories.

```json
{
  "app": "hive.forum",
  "v": 1,
  "type": "category_action",
  "action": "create|update|delete",
  "slug": "category-slug",
  "name": "Category Display Name",
  "description": "Category description",
  "sort_order": 10
}
```

## Data Validation Rules

1. **Content Length**: Configurable max length (default 2048 chars for topics, 1024 for posts)
2. **Title Length**: Max 200 characters
3. **Category Slug**: Lowercase, alphanumeric + hyphens only
4. **Tags**: Max 5 tags per topic, each max 50 chars
5. **Mentions**: Max 10 mentions per operation

## Database Storage Strategy

Topics and posts will be stored with hierarchical relationships:

- Topics are top-level entities with unique transaction IDs
- Posts reference their parent topic via `topic_id`
- Direct replies reference the post they're replying to via `reply_to`
- Categories are managed separately with slug-based identification

## Backward Compatibility

The forum protocol is completely separate from Hive Micro and uses a different APP_ID, ensuring no conflicts or cross-contamination of data.

