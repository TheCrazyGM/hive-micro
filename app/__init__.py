import os

from flask import Flask
from nectar.hive import Hive
from nectar.instance import set_shared_hive_instance

from .extensions import cache
import atexit

from .helpers import start_block_watcher, stop_block_watcher
from .models import db
from markupsafe import Markup, escape
from datetime import datetime


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
    # Content length limit (characters) for display and posting UI
    try:
        app.config["CONTENT_MAX_LEN"] = int(os.environ.get("HIVE_MICRO_MAX_LEN", "512"))
    except Exception:
        app.config["CONTENT_MAX_LEN"] = 512

    db.init_app(app)
    cache.init_app(app)
    app.config["APP_ID"] = os.environ.get("HIVE_MICRO_APP_ID", "hive.micro")

    # Initialize Hive instance with optional custom nodes
    nodes_env = os.environ.get("HIVE_NODES", "").strip()
    if nodes_env:
        nodes = [n.strip() for n in nodes_env.split(",") if n.strip()]
        hv = Hive(node=nodes, num_retries=5, num_retries_call=3, timeout=15)
        set_shared_hive_instance(hv)

    # Blueprints: API and UI kept separate for modularity
    from .api import api_bp
    from .ui import ui_bp

    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(ui_bp)

    with app.app_context():
        db.create_all()

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
