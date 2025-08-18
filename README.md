# Hive Micro

Hive Micro is a lightweight micro-posting web app for the Hive blockchain. It features Hive Keychain login, a real-time-ish timeline backed by a local database of `custom_json` messages, following filtering, mentions, tags, Markdown rendering with HTML sanitization, avatars, and a clean Bootstrap UI.

## Features

- **Login with Hive Keychain**: Sign a server-provided challenge; backend verifies signature using `PublicKey.verify_message()`.
- **Timeline feed**: Paginated timeline with optional filters.
  - Toggle: **Following only** (shows posts from accounts you follow).
  - Filter by **#tag** via URL query.
- **Single post view**: Shows a post and its replies (thread view).
- **Replying**: Quick reply flow pre-fills `@author` and references parent trx id.
- **Mentions**: Backend endpoints for mentions count and list; client-side extraction at post time.
- **Markdown + basic HTML**: Server renders and sanitizes to safe HTML using `markdown` + `bleach`.
- **Avatars**: Small round avatars via `https://images.hive.blog/u/<username>/avatar`.
- **Caching**: Simple in-memory cache for frequently used data (e.g., following list).

## Tech stack

- Backend: Flask, SQLAlchemy, Flask-Caching
- Hive lib: nectar (`Hive`, `Account`, shared instance)
- Crypto verify: `nectargraphenebase`
- Frontend: Vanilla JS + Bootstrap

## Environment configuration

See `sample.env` for all options. Key variables from `app.py`:

- **FLASK_SECRET_KEY**: Flask session secret
- **DATABASE_URL**: SQLAlchemy connection string (default `sqlite:///app.db`)
- **CACHE_TYPE**: Flask-Caching backend (default `SimpleCache`)
- **CACHE_DEFAULT_TIMEOUT**: Cache TTL in seconds (default `60`)
- **HIVE_MICRO_APP_ID**: App id for `custom_json` (default `hive.micro`)
- **HIVE_NODES**: Optional comma-separated list of Hive API nodes
- **HIVE_MICRO_WATCHER**: Optional flag to enable background block watcher (if applicable)

Example `sample.env` already included in the repo.

## Running locally

1. Create and activate a virtual environment
2. Install dependencies (managed via `uv`/`pyproject.toml`)
3. Copy `sample.env` to `.env` (or export vars)
4. Run the app

Example using uv:

```bash
uv sync
cp sample.env .env
uv run flask --app app run --debug
```

Then visit `http://127.0.0.1:5000/`.

## Key endpoints (server)

- `GET /api/v1/timeline`
  - Query params: `limit`, `cursor` (ISO timestamp), `following=1`, `tag`
  - Returns: items with `content` and sanitized `html`
- `GET /api/v1/post/<trx_id>`: Returns a single item and its `replies`
- `GET /api/v1/mentions/count`
- `GET /api/v1/mentions/list`
- `POST /login`: Verifies Keychain signature and establishes a session

UI routes:

- `/feed` main feed
- `/p/<trx_id>` single post page
- `/new_post` composer (supports replying via query params)
- `/u/<username>` basic profile view

## Content rendering and safety

- Server: `markdown_render()`
  - Pre-linkifies `@user` and `#tag` to internal links
  - Renders Markdown
  - Sanitizes HTML via Bleach (safe tags/attrs/protocols only)
- Client: prefers `item.html` from backend; falls back to linkified plain text

## Following filter

- Uses `Account(<user>).get_following()` from nectar; results are normalized and cached briefly.

## Development notes

- Frontend JS lives in `static/js/`:
  - `feed.js` timeline, pagination, toggle, tag filter
  - `post_view.js` single post + replies
  - `post.js` composer and reply preview
- Templates in `templates/` with Bootstrap styling

## License

See `LICENSE`.
