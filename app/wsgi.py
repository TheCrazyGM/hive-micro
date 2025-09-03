"""
WSGI entrypoint for running the app with Gunicorn or other WSGI servers.

Usage (example):
  gunicorn -w 4 -b 0.0.0.0:8000 app.wsgi:app

This module exposes `app`, created via the application's factory.
"""

import os

from dotenv import load_dotenv

from . import create_app

load_dotenv()

# Create the Flask application via the factory
app = create_app()


if __name__ == "__main__":
    # Optional local run for quick checks
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
