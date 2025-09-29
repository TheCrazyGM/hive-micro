# Hive Micro Project Overview
- Purpose: Flask-based micro-posting web app for the Hive blockchain with timeline, mentions, moderation, and Markdown rendering.
- Architecture: Flask app factory (`app/__init__.py`) registers API (`app/api.py`) under `/api/v1` and UI (`app/ui.py`); SQLAlchemy models in `app/models.py`; background watcher thread ingests Hive blocks (`app/helpers.py`, `app/watcher.py`).
- Frontend: Bootstrap templates in `app/templates/`, JS utilities in `app/static/js/` for feed, mentions, etc.
- Key integrations: Hive blockchain via `hive-nectar`, Flask-Caching, Markdown + Bleach for safe rendering, Hive Keychain login.
- Deployment: `run.py` for dev server; `Dockerfile` + `docker-compose.yml` for containerized deployment running Gunicorn by default.
