# Hive Micro Style & Conventions
- Backend: Modern Python (>=3.13). Uses type hints selectively but not pervasive. Follow Flask patterns with blueprints. Logging via `current_app.logger`.
- Formatting/Linting: Uses Ruff for linting and formatting (`ruff check --fix`, `ruff format`). HTML/CSS/JS formatted via djhtml/djcss/djjs (pre-commit).
- Naming: snake_case for functions/modules, PascalCase for SQLAlchemy models. Avoid unused imports; prefer explicit logging messages.
- Templates: Bootstrap-based, stored in `app/templates/` with partials and layout structure.
