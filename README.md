# Hive Micro

Hive Micro is a lightweight micro-posting web app for the Hive blockchain. It supports Hive Keychain login, a local database of `custom_json` posts, a timeline with following and tag filters, mentions, and safe Markdown rendering — all wrapped in a clean Bootstrap UI.

## Features

- Login with Hive Keychain: server challenge + signature verification on backend.
- Timeline: pagination, “Following only” toggle, and tag filter.
- Single post view: post + replies (thread).
- Mentions: unread count and mentions feed.
- Composer: create posts and replies; client extracts mentions/tags.
- Markdown rendering: sanitized HTML via Python-Markdown + Bleach.
- Caching: lightweight Flask-Caching for small computed results (e.g., following list).

## Architecture

- App factory: `app.create_app()` configures extensions and blueprints.
- Blueprints:
  - API: `app/api.py` mounted at `/api/v1`.
  - UI: `app/ui.py` serving pages.
- Templates:
  - Layout: `templates/layout/base.html`.
  - Partials: `templates/partials/{navbar,footer,posts}.html`.
  - Pages: `templates/pages/*.html`.
  - Errors: `templates/errors/*.html`.
- Background watcher: a small thread that ingests Hive blocks and stores posts with a matching `APP_ID`.

## Environment configuration

Copy `sample.env` to `.env` and adjust as needed.

- `FLASK_SECRET_KEY`: Flask session secret (default dev key).
- `DATABASE_URL`: SQLAlchemy database URL (default `sqlite:///app.db`).
- `CACHE_TYPE`: Flask-Caching backend (default `SimpleCache`).
- `CACHE_DEFAULT_TIMEOUT`: Cache TTL seconds (default `60`).
- `HIVE_MICRO_APP_ID`: App id for `custom_json` (default `hive.micro`).
- `HIVE_NODES`: Optional comma-separated list of Hive API nodes.
- `HIVE_MICRO_WATCHER`: `1` to enable background watcher, `0` to disable (default `1`).

Notes
- The backend filters ingested posts using `APP_ID` and the frontend broadcasts with the same id. The value is injected for client scripts as `window.HIVE_APP_ID`.
- When debug auto-reload is active, the watcher is guarded to avoid duplicate threads.

## Quickstart

Using `uv` (preferred):

```bash
uv sync
cp sample.env .env
uv run python run.py   # runs on port 8000 by default
```

Using pip:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp sample.env .env
python run.py
```

Visit `http://127.0.0.1:8000/`.

To disable the watcher during local dev:

```bash
HIVE_MICRO_WATCHER=0 python run.py
```

## API endpoints

Base URL: `/api/v1`

- `GET /timeline`
  - Params: `limit`, `cursor` (ISO), `following=1`, `tag`
- `GET /timeline/new_count`
- `GET /post/<trx_id>`
- `GET /mentions`
- `GET /mentions/count`
- `POST /mentions/seen`
- `GET /tags/trending`
- `GET /status` — returns `{ app_id, messages, last_block }`
- `POST /login` — verifies Keychain signature and creates session

UI routes

- `/` login page
- `/feed` timeline
- `/mentions` mentions feed
- `/new_post` composer (supports reply via query params `?reply_to=<trx>&author=<name>`)
- `/p/<trx_id>` single post + replies
- `/u/<username>` basic profile

## Data model (SQLite by default)

- `messages`: posts (`trx_id`, `block_num`, `timestamp`, `author`, `content`, optional `mentions/tags` as JSON, `reply_to`, `raw_json`).
- `checkpoints`: last processed block for ingestion.
- `mention_state`: per-username `last_seen` to compute unread counts.

## Posting flow

- Client (`static/js/post.js`) builds a `custom_json` with:
  - `id = window.HIVE_APP_ID`
  - payload: `{ app: window.HIVE_APP_ID, v: 1, type: 'post', content, mentions, tags, reply_to }`
- Broadcast via Hive Keychain.
- Watcher ingests blocks and stores posts where `payload.id == APP_ID`.

## Rendering and safety

- Server `helpers.markdown_render()`:
  - Converts `@user` and `#tag` to internal links pre-Markdown.
  - Renders Markdown and sanitizes HTML via Bleach.
- Frontend prefers server-provided `item.html` and falls back to linkified text.

## Refactor highlights (current)

- Split routes into `api.py` and `ui.py` blueprints; API mounted at `/api/v1`.
- Modular background watcher using the real app context and clean shutdown at exit.
- Template organization with layout/partials/pages/errors; reusable post card macros.
- Single source of truth for APP_ID across backend and frontend.

## License

See `LICENSE`.
