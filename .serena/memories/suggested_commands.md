# Hive Micro Suggested Commands
- Install deps (uv): `uv sync`
- Run dev server: `uv run python run.py`
- Run with watcher disabled locally: `HIVE_MICRO_WATCHER=0 uv run python run.py`
- Run watcher module manually: `uv run python -m app.watcher`
- Run lint & format (Ruff): `uv run ruff check --fix` and `uv run ruff format`
- Normalize HTML/JS/CSS via pre-commit tools: `uv run djhtml app/templates --in-place`, `uv run djjs app/static/js --in-place`
- Container build: `docker build -t hive-micro .`
- Compose stack: `docker compose up --build`
