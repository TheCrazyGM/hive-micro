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

from .helpers import _get_following_usernames, markdown_render
from .models import Message, Moderation, Appreciation, db

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
    # Redirect to unified public profile view for the logged-in user
    return redirect(url_for("ui.public_profile", username=session["username"]))


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
    # Follow state
    is_following = False
    is_self = False
    if "username" in session:
        cur = (session["username"] or "").strip().lower()
        target = uname.strip().lower()
        is_self = cur == target
        if not is_self:
            try:
                flw = _get_following_usernames(cur) or set()
                is_following = target in flw
            except Exception:
                is_following = False
    return render_template(
        "pages/user_profile.html",
        username=uname,
        profile=prof,
        raw=meta,
        is_following=is_following,
        is_self=is_self,
    )


@ui_bp.route("/p/<trx_id>")
def post_page(trx_id: str):
    if not trx_id:
        return redirect(url_for("ui.index"))
    # Server-render the post and its replies as a baseline; client JS can enhance
    m = Message.query.filter_by(trx_id=trx_id).first()
    if not m:
        return render_template("errors/404.html"), 404
    # Moderation logic
    mod = Moderation.query.filter_by(trx_id=trx_id).first()
    hidden = bool(mod and mod.visibility == "hidden")
    is_mod = session.get("username", "").lower() in (
        os.environ.get("HIVE_MICRO_MODERATORS", "").lower().split(",")
        if os.environ.get("HIVE_MICRO_MODERATORS")
        else []
    )
    if hidden and not is_mod:
        item = {
            "trx_id": m.trx_id,
            "timestamp": m.timestamp.isoformat(),
            "author": m.author,
            "removed": True,
            "mod_reason": mod.mod_reason if mod and mod.mod_reason else None,
        }
        replies = []
        return render_template(
            "pages/post.html", trx_id=trx_id, item=item, replies=replies, is_hidden=True
        )
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
        if not (
            Moderation.query.filter_by(trx_id=r.trx_id).first()
            and Moderation.query.filter_by(trx_id=r.trx_id).first().visibility
            == "hidden"
        )
    ]

    # Heart count aggregation for main post and replies
    heart_ids = [m.trx_id] + [r["trx_id"] for r in replies]
    counts_map = {}
    viewer_hearted_map = {}
    if heart_ids:
        rows = (
            db.session.query(Appreciation.trx_id, db.func.count(Appreciation.id))
            .filter(Appreciation.trx_id.in_(heart_ids))
            .group_by(Appreciation.trx_id)
            .all()
        )
        counts_map = {trx: cnt for trx, cnt in rows}
        if "username" in session:
            viewer = session["username"].lower()
            you_rows = (
                db.session.query(Appreciation.trx_id)
                .filter(Appreciation.trx_id.in_(heart_ids))
                .filter(Appreciation.username == viewer)
                .all()
            )
            viewer_hearted_map = {r[0] for r in you_rows}

    # Add heart data to main item
    item["hearts"] = int(counts_map.get(m.trx_id, 0))
    item["viewer_hearted"] = bool(m.trx_id in viewer_hearted_map)

    # Add heart data to replies
    for r in replies:
        r["hearts"] = int(counts_map.get(r["trx_id"], 0))
        r["viewer_hearted"] = bool(r["trx_id"] in viewer_hearted_map)
    return render_template(
        "pages/post.html", trx_id=trx_id, item=item, replies=replies, is_hidden=hidden
    )


@ui_bp.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("ui.index"))


@ui_bp.route("/moderation")
def moderation_page():
    # mods only
    if not session.get("username"):
        return redirect(url_for("ui.index"))
    uname = session.get("username", "").lower()
    from flask import current_app

    if uname not in (current_app.config.get("MODERATORS") or []):
        return redirect(url_for("ui.feed"))
    return render_template("pages/mod_dashboard.html")


@ui_bp.route("/audit")
def audit_page():
    # Audit page is visible to logged-in users only
    if not session.get("username"):
        return redirect(url_for("ui.index"))
    return render_template("pages/audit.html")


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
