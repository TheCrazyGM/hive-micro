import json
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, session

from .helpers import (
    _get_following_usernames,
    _parse_login_payload,
    _parse_timestamp,
    _verify_signature_and_key,
    markdown_render,
)
from .models import (
    Checkpoint,
    MentionState,
    Message,
    Moderation,
    ModerationAction,
    db,
)

api_bp = Blueprint("api", __name__)


def _hidden_trx_subquery():
    return db.session.query(Moderation.trx_id).filter(Moderation.visibility == "hidden")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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

    q = (
        Message.query.filter(~Message.trx_id.in_(_hidden_trx_subquery()))
        .order_by(Message.timestamp.desc())
        .limit(window)
    )
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
    include_hidden = request.args.get("include_hidden") == "1"
    is_mod = session.get("username", "").lower() in (
        current_app.config.get("MODERATORS") or []
    )
    if not (include_hidden and is_mod):
        q = q.filter(~Message.trx_id.in_(_hidden_trx_subquery()))
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
    max_len = int(current_app.config.get("CONTENT_MAX_LEN", 512))
    posts = q.all()
    include_hidden = request.args.get("include_hidden") == "1"
    is_mod = session.get("username", "").lower() in (
        current_app.config.get("MODERATORS") or []
    )
    for m in posts:
        hidden_flag = False
        mod_reason = None
        if include_hidden and is_mod:
            mod = Moderation.query.filter_by(trx_id=m.trx_id).first()
            hidden_flag = bool(mod and mod.visibility == "hidden")
            mod_reason = mod.mod_reason if (mod and mod.mod_reason) else None
        text = (m.content or "")[:max_len]
        items.append(
            {
                "trx_id": m.trx_id,
                "block_num": m.block_num,
                "timestamp": m.timestamp.isoformat(),
                "author": m.author,
                "type": m.type,
                "content": text,
                "html": markdown_render(text),
                "mentions": json.loads(m.mentions) if m.mentions else [],
                "tags": json.loads(m.tags) if m.tags else [],
                "reply_to": m.reply_to,
                **(
                    {"hidden": hidden_flag, "mod_reason": mod_reason}
                    if (include_hidden and is_mod)
                    else {}
                ),
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
    include_hidden = request.args.get("include_hidden") == "1"
    is_mod = session.get("username", "").lower() in (
        current_app.config.get("MODERATORS") or []
    )
    if not (include_hidden and is_mod):
        q = q.filter(~Message.trx_id.in_(_hidden_trx_subquery()))

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
    # Moderation: show removed stub to non-moderators
    mod = Moderation.query.filter_by(trx_id=trx_id).first()
    hidden = bool(mod and mod.visibility == "hidden")
    is_mod = session.get("username", "").lower() in (
        current_app.config.get("MODERATORS") or []
    )
    if hidden and not is_mod:
        reason = mod.mod_reason if mod and mod.mod_reason else None
        return jsonify(
            {
                "item": {
                    "trx_id": m.trx_id,
                    "timestamp": m.timestamp.isoformat(),
                    "author": m.author,
                    "removed": True,
                    "mod_reason": reason,
                },
                "replies": [],
            }
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


@api_bp.route("/mod/log/<trx_id>")
def mod_log(trx_id: str):
    if "username" not in session:
        return jsonify({"items": []})
    moderator = session["username"].lower()
    if moderator not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"items": []})
    rows = (
        ModerationAction.query.filter_by(trx_id=trx_id)
        .order_by(ModerationAction.created_at.desc())
        .all()
    )
    items = [
        {
            "id": a.id,
            "trx_id": a.trx_id,
            "moderator": a.moderator,
            "action": a.action,
            "reason": a.reason,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]
    return jsonify({"items": items})


@api_bp.route("/mentions/count")
def api_mentions_count():
    if "username" not in session:
        return jsonify({"count": 0}), 401
    uname = session["username"].lower()
    like_pattern = f'%"{uname}"%'
    q = Message.query.filter(Message.mentions.like(like_pattern))
    q = q.filter(~Message.trx_id.in_(_hidden_trx_subquery()))
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
    now = _utcnow_naive()
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
    max_len = int(current_app.config.get("CONTENT_MAX_LEN", 512))
    for m in q.all():
        text = (m.content or "")[:max_len]
        items.append(
            {
                "trx_id": m.trx_id,
                "block_num": m.block_num,
                "timestamp": m.timestamp.isoformat(),
                "author": m.author,
                "type": m.type,
                "content": text,
                "html": markdown_render(text),
                "mentions": json.loads(m.mentions) if m.mentions else [],
                "tags": json.loads(m.tags) if m.tags else [],
                "reply_to": m.reply_to,
            }
        )

    return jsonify({"items": items, "count": len(items)})


@api_bp.route("/mod/list")
def mod_list():
    if "username" not in session:
        return jsonify({"items": []}), 401
    uname = session["username"].lower()
    if uname not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"items": []}), 403
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 100))
    only_hidden = request.args.get("only_hidden") == "1"
    cursor = request.args.get("cursor")
    q = Message.query
    if cursor:
        try:
            dt = datetime.fromisoformat(cursor)
            q = q.filter(Message.timestamp < dt)
        except Exception:
            pass
    q = q.order_by(Message.timestamp.desc()).limit(limit)
    rows = q.all()
    items = []
    for m in rows:
        mod = Moderation.query.filter_by(trx_id=m.trx_id).first()
        hidden = bool(mod and mod.visibility == "hidden")
        if only_hidden and not hidden:
            continue
        items.append(
            {
                "trx_id": m.trx_id,
                "timestamp": m.timestamp.isoformat(),
                "author": m.author,
                "content": m.content,
                "tags": json.loads(m.tags) if m.tags else [],
                "hidden": hidden,
                "mod_reason": (mod.mod_reason if (mod and mod.mod_reason) else None),
            }
        )
    return jsonify({"items": items})


@api_bp.route("/login", methods=["POST"])
def login():
    signature, username, pubkey, message, err, status = _parse_login_payload()
    if err is not None:
        return err, status
    # Enforce freshness window on the signed message (ISO timestamp)
    try:
        msg_dt = _parse_timestamp(str(message))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        skew = abs((now - msg_dt).total_seconds())
        max_skew = int(current_app.config.get("LOGIN_MAX_SKEW", 120))
        if skew > max_skew:
            return jsonify(
                {"success": False, "error": "Stale or future-dated proof."}
            ), 400
    except Exception:
        return jsonify({"success": False, "error": "Invalid proof timestamp."}), 400

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
@api_bp.route("/mod/hide", methods=["POST"])
def mod_hide():
    if "username" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    moderator = session["username"].lower()
    if moderator not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"success": False, "error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    trx_id = (data.get("trx_id") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not trx_id:
        return jsonify({"success": False, "error": "missing trx_id"}), 400
    if current_app.config.get("MOD_REASON_REQUIRED") and not reason:
        return jsonify({"success": False, "error": "reason required"}), 400
    # Optional signature verification
    if current_app.config.get("MOD_REQUIRE_SIGNATURE"):
        sig = (data.get("signature") or "").strip()
        pubkey = (data.get("pubkey") or "").strip()
        message = (data.get("message") or "").strip()
        if not (sig and pubkey and message):
            return jsonify({"success": False, "error": "signature required"}), 400
        ok, invalid = _verify_signature_and_key(moderator, pubkey, message, sig)
        if not ok:
            return jsonify({"success": False, "error": "bad signature"}), 401
    act = ModerationAction(
        trx_id=trx_id,
        moderator=moderator,
        action="hide",
        reason=reason,
        created_at=_utcnow_naive(),
        sig_message=data.get("message"),
        sig_pubkey=data.get("pubkey"),
        sig_value=data.get("signature"),
    )
    db.session.add(act)
    quorum = int(current_app.config.get("MOD_QUORUM", 1))
    hidden = False
    # Determine last unhide cutoff so approvals reset after an unhide
    last_unhide = (
        db.session.query(ModerationAction.created_at)
        .filter(
            ModerationAction.trx_id == trx_id,
            ModerationAction.action == "unhide",
        )
        .order_by(ModerationAction.created_at.desc())
        .first()
    )
    cutoff = last_unhide[0] if last_unhide else None
    # Count distinct moderators approving hide after cutoff
    approvals_q = db.session.query(ModerationAction.moderator).filter(
        ModerationAction.trx_id == trx_id,
        ModerationAction.action == "hide",
    )
    if cutoff is not None:
        approvals_q = approvals_q.filter(ModerationAction.created_at > cutoff)
    approvals = approvals_q.distinct().count()
    if quorum <= 1:
        mod = Moderation.query.filter_by(trx_id=trx_id).first()
        if mod is None:
            mod = Moderation(
                trx_id=trx_id,
                visibility="hidden",
                mod_by=moderator,
                mod_reason=reason,
                mod_at=_utcnow_naive(),
            )
            db.session.add(mod)
        else:
            mod.visibility = "hidden"
            mod.mod_by = moderator
            mod.mod_reason = reason
            mod.mod_at = _utcnow_naive()
        hidden = True
    else:
        if approvals >= quorum:
            mod = Moderation.query.filter_by(trx_id=trx_id).first()
            if mod is None:
                mod = Moderation(
                    trx_id=trx_id,
                    visibility="hidden",
                    mod_by=moderator,
                    mod_reason=reason,
                    mod_at=_utcnow_naive(),
                )
                db.session.add(mod)
            else:
                mod.visibility = "hidden"
                mod.mod_by = moderator
                mod.mod_reason = reason
                mod.mod_at = _utcnow_naive()
            hidden = True
    db.session.commit()
    return jsonify(
        {"success": True, "hidden": hidden, "quorum": quorum, "approvals": approvals}
    )


@api_bp.route("/mod/unhide", methods=["POST"])
def mod_unhide():
    if "username" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    moderator = session["username"].lower()
    if moderator not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"success": False, "error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    trx_id = (data.get("trx_id") or "").strip()
    if not trx_id:
        return jsonify({"success": False, "error": "missing trx_id"}), 400
    # Optional signature verification
    if current_app.config.get("MOD_REQUIRE_SIGNATURE"):
        sig = (data.get("signature") or "").strip()
        pubkey = (data.get("pubkey") or "").strip()
        message = (data.get("message") or "").strip()
        if not (sig and pubkey and message):
            return jsonify({"success": False, "error": "signature required"}), 400
        ok, invalid = _verify_signature_and_key(moderator, pubkey, message, sig)
        if not ok:
            return jsonify({"success": False, "error": "bad signature"}), 401
    act = ModerationAction(
        trx_id=trx_id,
        moderator=moderator,
        action="unhide",
        created_at=_utcnow_naive(),
        sig_message=data.get("message"),
        sig_pubkey=data.get("pubkey"),
        sig_value=data.get("signature"),
    )
    db.session.add(act)
    mod = Moderation.query.filter_by(trx_id=trx_id).first()
    if mod is not None:
        mod.visibility = "public"
        mod.mod_by = moderator
        mod.mod_reason = None
        mod.mod_at = _utcnow_naive()
    db.session.commit()
    return jsonify({"success": True})
