import json
from datetime import datetime

from flask import Blueprint, jsonify, request, session, current_app

from .helpers import (
    _get_following_usernames,
    _parse_login_payload,
    _verify_signature_and_key,
    markdown_render,
)
from .models import Checkpoint, Message, MentionState, db


api_bp = Blueprint("api", __name__)


@api_bp.route("/tags/trending")
def api_tags_trending():
    try:
        window = max(50, min(int(request.args.get("window", 500)), 5000))
    except Exception:
        window = 500
    try:
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
    except Exception:
        limit = 10

    q = Message.query.order_by(Message.timestamp.desc()).limit(window)
    rows = q.all()
    counts: dict[str, int] = {}
    for m in rows:
        try:
            if not m.tags:
                continue
            tg = json.loads(m.tags)
            if isinstance(tg, list):
                for t in tg:
                    key = str(t).strip().lower()
                    if not key:
                        continue
                    counts[key] = counts.get(key, 0) + 1
        except Exception:
            continue

    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    items = [{"tag": k, "count": v} for k, v in top]
    return jsonify({"items": items, "count": len(items)})


@api_bp.route("/timeline")
def api_timeline():
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 100))

    cursor = request.args.get("cursor")
    following_flag = request.args.get("following", "0") == "1"
    tag_filter = request.args.get("tag")

    q = Message.query
    if cursor:
        try:
            dt = datetime.fromisoformat(cursor)
            q = q.filter(Message.timestamp < dt)
        except Exception:
            pass

    if following_flag and session.get("username"):
        flw = _get_following_usernames(session["username"]) or set()
        if flw:
            q = q.filter(Message.author.in_(list(flw)))
        else:
            q = q.filter(db.text("0"))

    if tag_filter:
        like_pattern = f'%"{tag_filter.lower()}"%'
        q = q.filter(Message.tags.like(like_pattern))

    q = q.order_by(Message.timestamp.desc()).limit(limit)

    items = []
    posts = q.all()
    for m in posts:
        items.append(
            {
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
        )

    return jsonify({"items": items, "count": len(items)})


@api_bp.route("/timeline/new_count")
def api_timeline_new_count():
    since = request.args.get("since")
    if not since:
        return jsonify({"count": 0}), 400
    try:
        dt = datetime.fromisoformat(since)
    except Exception:
        return jsonify({"count": 0}), 400

    following_flag = request.args.get("following", "0") == "1"
    tag_filter = request.args.get("tag")

    q = Message.query.filter(Message.timestamp > dt)

    if following_flag and session.get("username"):
        flw = _get_following_usernames(session["username"]) or set()
        if flw:
            q = q.filter(Message.author.in_(list(flw)))
        else:
            q = q.filter(db.text("0"))

    if tag_filter:
        like_pattern = f'%"{tag_filter.lower()}"%'
        q = q.filter(Message.tags.like(like_pattern))

    cnt = q.count()
    latest = (
        q.order_by(Message.timestamp.desc()).first().timestamp.isoformat()
        if cnt > 0
        else None
    )
    return jsonify({"count": cnt, "latest": latest})


@api_bp.route("/post/<trx_id>")
def api_post(trx_id: str):
    if not trx_id:
        return jsonify({"error": "missing trx_id"}), 400
    m = Message.query.filter_by(trx_id=trx_id).first()
    if not m:
        return jsonify({"error": "not found"}), 404
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
    replies_q = Message.query.filter_by(reply_to=trx_id).order_by(
        Message.timestamp.asc()
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
        for r in replies_q.all()
    ]
    return jsonify({"item": item, "replies": replies})


@api_bp.route("/mentions/count")
def api_mentions_count():
    if "username" not in session:
        return jsonify({"count": 0}), 401
    uname = session["username"].lower()
    like_pattern = f'%"{uname}"%'
    q = Message.query.filter(Message.mentions.like(like_pattern))
    state = MentionState.query.get(uname)
    if state and state.last_seen:
        q = q.filter(Message.timestamp > state.last_seen)
    cnt = q.count()
    return jsonify({"count": cnt})


@api_bp.route("/mentions/seen", methods=["POST"])
def api_mentions_seen():
    if "username" not in session:
        return jsonify({"success": False}), 401
    uname = session["username"].lower()
    now = datetime.now()
    state = MentionState.query.get(uname)
    if state is None:
        state = MentionState(username=uname, last_seen=now)
        db.session.add(state)
    else:
        state.last_seen = now
    db.session.commit()
    return jsonify({"success": True, "last_seen": now.isoformat()})


@api_bp.route("/status")
def api_status():
    total = Message.query.count()
    ck = Checkpoint.query.get(1)
    return jsonify(
        {
            "messages": total,
            "last_block": ck.last_block if ck else 0,
            "app_id": current_app.config.get("APP_ID", "hive.micro"),
        }
    )


@api_bp.route("/mentions")
def api_mentions():
    if "username" not in session:
        return jsonify({"items": [], "count": 0}), 401

    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 100))

    cursor = request.args.get("cursor")

    q = Message.query
    if cursor:
        try:
            dt = datetime.fromisoformat(cursor)
            q = q.filter(Message.timestamp < dt)
        except Exception:
            pass

    uname = session["username"].lower()
    like_pattern = f'%"{uname}"%'
    q = q.filter(Message.mentions.like(like_pattern))

    q = q.order_by(Message.timestamp.desc()).limit(limit)

    items = []
    for m in q.all():
        items.append(
            {
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
        )

    return jsonify({"items": items, "count": len(items)})


@api_bp.route("/login", methods=["POST"])
def login():
    signature, username, pubkey, message, err, status = _parse_login_payload()
    if err is not None:
        return err, status

    try:
        valid, invalid_resp = _verify_signature_and_key(
            username, pubkey, message, signature
        )
    except Exception as e:
        return jsonify(
            {"success": False, "error": f"Verification error: {str(e)}"}
        ), 400
    if not valid:
        return jsonify(invalid_resp), 401

    session["username"] = username
    return jsonify({"success": True, "username": username})


# With url_prefix '/api/v1', '/login' is exposed as '/api/v1/login'
