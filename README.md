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
- `HIVE_MICRO_MAX_LEN`: Maximum characters for composer and previews (default `512`).
- `HIVE_MICRO_LOGIN_MAX_SKEW`: Max login proof skew in seconds (default `120`).
- Cookie security (prod):
  - `SESSION_COOKIE_SECURE`: Set to `1` when serving over HTTPS.
  - `SESSION_COOKIE_SAMESITE`: `Lax` (default), `Strict`, or `None`.
- Moderation:
  - `HIVE_MICRO_MODERATORS`: Comma-separated moderator usernames (lowercase).
  - `HIVE_MICRO_MOD_QUORUM`: Number of approvals required to hide a post (default `1`).
  - `HIVE_MICRO_MOD_REASON_REQUIRED`: Require a reason to hide (0/1, default `0`).
  - `HIVE_MICRO_MOD_REQUIRE_SIG`: Require per-action Keychain signature for moderator actions (0/1, default `0`).

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
- Moderation:
  - `POST /mod/hide` `{ trx_id, reason? }` — moderator-only, hides when approvals >= quorum
  - `POST /mod/unhide` `{ trx_id }` — moderator-only, restores visibility
  - `GET /mod/log/<trx_id>` — moderator-only action log for a post

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

Content length
- The composer enforces `HIVE_MICRO_MAX_LEN` on the client with a live counter.
- The API truncates content to this length for timeline and mentions responses so previews stay concise.
- The single post endpoint and server-rendered permalink show full content.

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
- UI polish: Replaced alerts with Bootstrap toasts; improved light/dark theme surfaces and transitions; high-contrast tag chips; smoother trending refresh without flicker; unified image scaling inside cards; New Post page now a card with Markdown tip and live counter.
 - Moderation (soft-hide): optional moderators with quorum; timelines exclude hidden posts; permalinks show a transparent “Removed by moderators” stub with optional reason; actions audited.

## License

See `LICENSE`.
