import json
import os

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    session,
    url_for,
)
from nectar.account import Account
from .models import Message
from .helpers import markdown_render


ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def index():
    if "username" in session:
        return redirect(url_for("ui.feed"))
    return render_template("pages/login.html")


@ui_bp.route("/feed")
def feed():
    if "username" not in session:
        return redirect(url_for("ui.index"))
    return render_template("pages/feed.html")


@ui_bp.route("/mentions")
def mentions_page():
    if "username" not in session:
        return redirect(url_for("ui.index"))
    return render_template("pages/mentions.html")


@ui_bp.route("/new_post")
def new_post():
    if "username" not in session:
        return redirect(url_for("ui.index"))
    return render_template("pages/new_post.html")


@ui_bp.route("/profile")
def profile():
    if "username" not in session:
        return redirect(url_for("ui.index"))
    username = session["username"]
    account = Account(username)
    meta = account.get("posting_json_metadata") or account.get("json_metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    profile = meta.get("profile") if isinstance(meta, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    return render_template(
        "pages/profile.html",
        username=username,
        profile=profile,
        raw=meta,
    )


@ui_bp.route("/u/<username>")
def public_profile(username: str):
    uname = (username or "").strip()
    if not uname:
        return redirect(url_for("ui.feed"))
    account = Account(uname)
    meta = account.get("posting_json_metadata") or account.get("json_metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    prof = meta.get("profile") if isinstance(meta, dict) else {}
    if not isinstance(prof, dict):
        prof = {}
    return render_template(
        "pages/user_profile.html", username=uname, profile=prof, raw=meta
    )


@ui_bp.route("/p/<trx_id>")
def post_page(trx_id: str):
    if not trx_id:
        return redirect(url_for("ui.index"))
    # Server-render the post and its replies as a baseline; client JS can enhance
    m = Message.query.filter_by(trx_id=trx_id).first()
    if not m:
        return render_template("errors/404.html"), 404
    item = {
        "trx_id": m.trx_id,
        "block_num": m.block_num,
        "timestamp": m.timestamp.isoformat(),
        "author": m.author,
        "type": m.type,
        "content": m.content,
        "html": markdown_render(m.content),
        "mentions": json.loads(m.mentions) if m.mentions else [],
        "tags": json.loads(m.tags) if m.tags else [],
        "reply_to": m.reply_to,
    }
    reps = (
        Message.query.filter_by(reply_to=trx_id).order_by(Message.timestamp.asc()).all()
    )
    replies = [
        {
            "trx_id": r.trx_id,
            "block_num": r.block_num,
            "timestamp": r.timestamp.isoformat(),
            "author": r.author,
            "type": r.type,
            "content": r.content,
            "html": markdown_render(r.content),
            "mentions": json.loads(r.mentions) if r.mentions else [],
            "tags": json.loads(r.tags) if r.tags else [],
            "reply_to": r.reply_to,
        }
        for r in reps
    ]
    return render_template("pages/post.html", trx_id=trx_id, item=item, replies=replies)


@ui_bp.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("ui.index"))


# --- Error handlers ---
@ui_bp.errorhandler(401)
def handle_401(error):
    return render_template("errors/401.html"), 401


@ui_bp.errorhandler(403)
def handle_403(error):
    return render_template("errors/403.html"), 403


@ui_bp.errorhandler(404)
def handle_404(error):
    return render_template("errors/404.html"), 404


@ui_bp.errorhandler(500)
def handle_500(error):
    return render_template("errors/500.html"), 500


if os.environ.get("ENABLE_ERROR_ROUTES", "1") == "1":

    @ui_bp.route("/error/401")
    def _error_401():
        abort(401)

    @ui_bp.route("/error/403")
    def _error_403():
        abort(403)

    @ui_bp.route("/error/404")
    def _error_404():
        abort(404)

    @ui_bp.route("/error/500")
    def _error_500():
        raise RuntimeError("Test 500 error page")
