import atexit
import os
import secrets
from datetime import datetime

from flask import Flask, abort, request, session
from markupsafe import Markup, escape

from .extensions import cache
from .helpers import start_block_watcher, stop_block_watcher
from .models import db


def create_app():
    app = Flask(__name__)
    # Use a stable secret so session cookies remain valid across reloads
    app.config["SECRET_KEY"] = os.environ.get(
        "FLASK_SECRET_KEY", "dev-secret-key-change-me"
    )
    # Database & Cache config
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///app.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config.setdefault("CACHE_TYPE", "SimpleCache")
    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", 60)
    # Security settings
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", False)
    # Allow overriding via environment
    scs = os.environ.get("SESSION_COOKIE_SAMESITE")
    if scs:
        app.config["SESSION_COOKIE_SAMESITE"] = scs
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
        "SESSION_COOKIE_SECURE", "0"
    ) in (
        "1",
        "true",
        "yes",
        "on",
    )
    # Login proof freshness window (seconds)
    try:
        app.config["LOGIN_MAX_SKEW"] = int(
            os.environ.get("HIVE_MICRO_LOGIN_MAX_SKEW", "120")
        )
    except Exception:
        app.config["LOGIN_MAX_SKEW"] = 120
    # Content length limit (characters) for display and posting UI
    try:
        app.config["CONTENT_MAX_LEN"] = int(os.environ.get("HIVE_MICRO_MAX_LEN", "512"))
    except Exception:
        app.config["CONTENT_MAX_LEN"] = 512
    # Moderation config
    mods = os.environ.get("HIVE_MICRO_MODERATORS", "").strip()
    app.config["MODERATORS"] = [u.strip().lower() for u in mods.split(",") if u.strip()]
    try:
        app.config["MOD_QUORUM"] = int(os.environ.get("HIVE_MICRO_MOD_QUORUM", "1"))
    except Exception:
        app.config["MOD_QUORUM"] = 1
    app.config["MOD_REASON_REQUIRED"] = os.environ.get(
        "HIVE_MICRO_MOD_REASON_REQUIRED", "0"
    ) in ("1", "true", "yes", "on")
    app.config["MOD_REQUIRE_SIGNATURE"] = os.environ.get(
        "HIVE_MICRO_MOD_REQUIRE_SIG", "0"
    ) in ("1", "true", "yes", "on")

    db.init_app(app)
    cache.init_app(app)
    app.config["APP_ID"] = os.environ.get("HIVE_MICRO_APP_ID", "hive.micro")

    # Initialize Hive instance with optional custom nodes
    app.config["HIVE_NODES"] = os.environ.get("HIVE_NODES", "").strip()

    # Blueprints: API and UI kept separate for modularity
    from .api import api_bp
    from .ui import ui_bp

    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(ui_bp)

    with app.app_context():
        db.create_all()

    # --- CSRF token setup and validation ---
    @app.before_request
    def _ensure_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)

    @app.after_request
    def _set_csrf_cookie(resp):
        # Double-submit cookie for frontend to read and send back in header
        token = session.get("csrf_token", "")
        resp.set_cookie(
            "XSRF-TOKEN",
            token,
            samesite="Lax",
            secure=app.config.get("SESSION_COOKIE_SECURE", False),
            httponly=False,
            path="/",
        )
        return resp

    @app.before_request
    def _csrf_protect():
        if request.method in (
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        ) and request.path.startswith("/api/v1/"):
            hdr = request.headers.get("X-CSRF-Token", "")
            cky = request.cookies.get("XSRF-TOKEN", "")
            tok = session.get("csrf_token", "")
            if not tok or hdr != tok or cky != tok:
                return abort(403)

    start_block_watcher(app)
    atexit.register(stop_block_watcher)

    # --- Jinja Filters ---
    @app.template_filter("tolocaltime")
    def jinja_to_local_time(value):
        """
        Render a <time> element that the client will convert to local time via JS.
        Accepts a datetime or an ISO-8601 string. Falls back to str(value).
        """
        iso = None
        if isinstance(value, datetime):
            # Always serialize to ISO-8601 with timezone if tz-aware; else as naive ISO
            try:
                iso = value.isoformat()
            except Exception:
                iso = str(value)
        else:
            # Attempt to keep as-is if it looks like a string
            try:
                iso = str(value)
            except Exception:
                iso = ""
        # Render a time tag with a recognizable class for client enhancement
        safe_iso = escape(iso)
        return Markup(f'<time class="ts-local" datetime="{safe_iso}">{safe_iso}</time>')

    return app
