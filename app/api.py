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
    ModerationState,
    Message,
    Moderation,
    ModerationAction,
    Appreciation,
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
    author_filter = request.args.get("author")

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

    # Optional author filter for profile timelines
    if author_filter:
        q = q.filter(Message.author == author_filter)

    q = q.order_by(Message.timestamp.desc()).limit(limit)

    items = []
    max_len = int(current_app.config.get("CONTENT_MAX_LEN", 512))
    posts = q.all()
    include_hidden = request.args.get("include_hidden") == "1"
    is_mod = session.get("username", "").lower() in (
        current_app.config.get("MODERATORS") or []
    )

    # --- Appreciation aggregation ---
    post_ids = [m.trx_id for m in posts]
    heart_counts_map = {}
    viewer_hearts = set()
    if post_ids:
        rows = (
            db.session.query(Appreciation.trx_id, db.func.count(Appreciation.id))
            .filter(Appreciation.trx_id.in_(post_ids))
            .group_by(Appreciation.trx_id)
            .all()
        )
        heart_counts_map = {trx: cnt for trx, cnt in rows}
        if session.get("username"):
            viewer = session["username"].lower()
            you_rows = (
                db.session.query(Appreciation.trx_id)
                .filter(Appreciation.trx_id.in_(post_ids))
                .filter(Appreciation.username == viewer)
                .all()
            )
            viewer_hearts = {r[0] for r in you_rows}

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
                "hearts": int(heart_counts_map.get(m.trx_id, 0)),
                "viewer_hearted": bool(m.trx_id in viewer_hearts),
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
    # Hearts aggregation for main post and replies
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
    replies_rows = replies_q.all()

    # Batch load hearts for item and replies
    heart_ids = [m.trx_id for m in replies_rows] + [m.trx_id]
    counts_map = {}
    you_set = set()
    if heart_ids:
        rows = (
            db.session.query(Appreciation.trx_id, db.func.count(Appreciation.id))
            .filter(Appreciation.trx_id.in_(heart_ids))
            .group_by(Appreciation.trx_id)
            .all()
        )
        counts_map = {trx: cnt for trx, cnt in rows}
        if session.get("username"):
            viewer = session["username"].lower()
            yr = (
                db.session.query(Appreciation.trx_id)
                .filter(Appreciation.trx_id.in_(heart_ids))
                .filter(Appreciation.username == viewer)
                .all()
            )
            you_set = {r[0] for r in yr}

    item["hearts"] = int(counts_map.get(m.trx_id, 0))
    item["viewer_hearted"] = bool(m.trx_id in you_set)
    replies = []
    for r in replies_rows:
        replies.append(
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
                "hearts": int(counts_map.get(r.trx_id, 0)),
                "viewer_hearted": bool(r.trx_id in you_set),
            }
        )
    return jsonify({"item": item, "replies": replies})


@api_bp.route("/heart", methods=["POST"])
def api_heart():
    if "username" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    trx_id = (data.get("trx_id") or "").strip()
    if not trx_id:
        return jsonify({"success": False, "error": "missing trx_id"}), 400
    m = Message.query.filter_by(trx_id=trx_id).first()
    if not m:
        return jsonify({"success": False, "error": "not found"}), 404
    viewer = session["username"].lower()
    # Insert if not exists
    exists = (
        db.session.query(Appreciation.id)
        .filter(Appreciation.trx_id == trx_id, Appreciation.username == viewer)
        .first()
    )
    if not exists:
        apprec = Appreciation(
            trx_id=trx_id,
            username=viewer,
            created_at=_utcnow_naive(),
        )
        db.session.add(apprec)
        db.session.commit()
    # Return updated count
    cnt = (
        db.session.query(db.func.count(Appreciation.id))
        .filter(Appreciation.trx_id == trx_id)
        .scalar()
    )
    return jsonify({"success": True, "hearts": int(cnt), "viewer_hearted": True})


@api_bp.route("/unheart", methods=["POST"])
def api_unheart():
    if "username" not in session:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    trx_id = (data.get("trx_id") or "").strip()
    if not trx_id:
        return jsonify({"success": False, "error": "missing trx_id"}), 400
    viewer = session["username"].lower()
    db.session.query(Appreciation).filter(
        Appreciation.trx_id == trx_id, Appreciation.username == viewer
    ).delete()
    db.session.commit()
    cnt = (
        db.session.query(db.func.count(Appreciation.id))
        .filter(Appreciation.trx_id == trx_id)
        .scalar()
    )
    return jsonify({"success": True, "hearts": int(cnt), "viewer_hearted": False})


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


@api_bp.route("/mod/audit")
def mod_audit_public():
    """Public moderation audit feed (auth may be required at UI).

    Returns recent moderation events ordered by moderation time (not post time).

    Query params:
    - limit: max items (default 20, max 100)
    - cursor: ISO timestamp to paginate before, based on moderation timestamp
    - status: 'all' | 'hidden' | 'pending'
    """
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 100))

    status = (request.args.get("status") or "all").strip().lower()
    if status not in ("all", "hidden", "pending"):
        status = "all"

    cursor = request.args.get("cursor")
    cursor_dt = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except Exception:
            cursor_dt = None

    items: list[dict] = []
    quorum = int(current_app.config.get("MOD_QUORUM", 1))

    # 1) Hidden items (from Moderation table), ordered by mod_at desc
    mod_q = Moderation.query.filter(Moderation.visibility == "hidden")
    if cursor_dt is not None:
        mod_q = mod_q.filter(Moderation.mod_at < cursor_dt)
    mod_q = mod_q.order_by(Moderation.mod_at.desc()).limit(limit)
    hidden_rows = mod_q.all()
    for mod in hidden_rows:
        m = Message.query.filter_by(trx_id=mod.trx_id).first()
        if not m:
            continue
        items.append(
            {
                "trx_id": m.trx_id,
                "author": m.author,
                "content": m.content,
                "tags": json.loads(m.tags) if m.tags else [],
                "hidden": True,
                "pending": False,
                "quorum": quorum,
                "mod_reason": mod.mod_reason,
                "mod_by": mod.mod_by,
                "mod_at": mod.mod_at.isoformat() if mod.mod_at else None,
                "approvals": None,
                "approvers": [],
                "last_action_at": None,
                "last_reason": None,
                "visibility": "hidden",
                # moderation timestamp used for pagination/sorting
                "mod_ts": mod.mod_at.isoformat() if mod.mod_at else None,
            }
        )

    # 2) Pending items based on ModerationAction (hide) since last unhide
    # Gather latest hide actions per trx_id, ordered by created_at desc
    act_q = ModerationAction.query.filter(ModerationAction.action == "hide")
    if cursor_dt is not None:
        act_q = act_q.filter(ModerationAction.created_at < cursor_dt)
    act_q = act_q.order_by(ModerationAction.created_at.desc()).limit(limit * 3)
    acts = act_q.all()

    seen_trx = set()
    for a in acts:
        if a.trx_id in seen_trx:
            continue
        seen_trx.add(a.trx_id)

        # Skip if already hidden
        mod = Moderation.query.filter_by(trx_id=a.trx_id).first()
        if mod and mod.visibility == "hidden":
            continue

        # Compute approvals since last unhide
        last_unhide = (
            db.session.query(ModerationAction.created_at)
            .filter(
                ModerationAction.trx_id == a.trx_id,
                ModerationAction.action == "unhide",
            )
            .order_by(ModerationAction.created_at.desc())
            .first()
        )
        cutoff = last_unhide[0] if last_unhide else None
        approvals_q = db.session.query(ModerationAction.moderator).filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            approvals_q = approvals_q.filter(ModerationAction.created_at > cutoff)
        approvals = approvals_q.distinct().count()
        pending = (quorum > 1) and (approvals > 0) and (approvals < quorum)
        if not pending:
            continue

        # Gather details
        hide_actions_q = ModerationAction.query.filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            hide_actions_q = hide_actions_q.filter(ModerationAction.created_at > cutoff)
        hide_actions = hide_actions_q.order_by(ModerationAction.created_at.desc()).all()
        approvers_list: list[str] = []
        latest_action_at = None
        latest_reason = None
        if hide_actions:
            seen_mods = set()
            for ha in hide_actions:
                if ha.moderator not in seen_mods:
                    approvers_list.append(ha.moderator)
                    seen_mods.add(ha.moderator)
            latest_action_at = hide_actions[0].created_at.isoformat()
            latest_reason = hide_actions[0].reason

        m = Message.query.filter_by(trx_id=a.trx_id).first()
        if not m:
            continue
        items.append(
            {
                "trx_id": m.trx_id,
                "author": m.author,
                "content": m.content,
                "tags": json.loads(m.tags) if m.tags else [],
                "hidden": False,
                "pending": True,
                "quorum": quorum,
                "mod_reason": None,
                "mod_by": None,
                "mod_at": None,
                "approvals": int(approvals),
                "approvers": approvers_list,
                "last_action_at": latest_action_at,
                "last_reason": latest_reason,
                "visibility": "public",
                # moderation timestamp used for pagination/sorting
                "mod_ts": latest_action_at,
            }
        )

    # Status filter and ordering by moderation timestamp
    def _pick_ts(x: dict) -> str | None:
        return x.get("mod_ts") or x.get("mod_at") or x.get("last_action_at")

    if status == "hidden":
        items = [it for it in items if it.get("hidden") is True]
    elif status == "pending":
        items = [it for it in items if it.get("pending") is True]
    else:
        items = [
            it
            for it in items
            if (it.get("hidden") or it.get("pending") or it.get("mod_reason"))
        ]

    items.sort(key=lambda it: _pick_ts(it) or "", reverse=True)

    # Pagination by moderation timestamp
    if cursor_dt is not None:
        items = [
            it
            for it in items
            if (_pick_ts(it) and datetime.fromisoformat(_pick_ts(it)) < cursor_dt)
        ]

    items = items[:limit]

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
    rows = q.all()

    # Appreciation aggregation for mentions list
    post_ids = [m.trx_id for m in rows]
    heart_counts_map = {}
    viewer_hearts = set()
    if post_ids:
        counts_rows = (
            db.session.query(Appreciation.trx_id, db.func.count(Appreciation.id))
            .filter(Appreciation.trx_id.in_(post_ids))
            .group_by(Appreciation.trx_id)
            .all()
        )
        heart_counts_map = {trx: cnt for trx, cnt in counts_rows}
        if session.get("username"):
            viewer = session["username"].lower()
            you_rows = (
                db.session.query(Appreciation.trx_id)
                .filter(Appreciation.trx_id.in_(post_ids))
                .filter(Appreciation.username == viewer)
                .all()
            )
            viewer_hearts = {r[0] for r in you_rows}

    for m in rows:
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
                "hearts": int(heart_counts_map.get(m.trx_id, 0)),
                "viewer_hearted": bool(m.trx_id in viewer_hearts),
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
    status = (request.args.get("status") or "all").strip().lower()
    if status not in ("all", "hidden", "pending"):
        status = "all"
    cursor = request.args.get("cursor")
    cursor_dt = None
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except Exception:
            cursor_dt = None

    quorum = int(current_app.config.get("MOD_QUORUM", 1))
    items: list[dict] = []

    # 1) Hidden items ordered by moderation time
    mod_q = Moderation.query.filter(Moderation.visibility == "hidden")
    if cursor_dt is not None:
        mod_q = mod_q.filter(Moderation.mod_at < cursor_dt)
    mod_q = mod_q.order_by(Moderation.mod_at.desc()).limit(limit)
    hidden_rows = mod_q.all()
    for mod in hidden_rows:
        m = Message.query.filter_by(trx_id=mod.trx_id).first()
        if not m:
            continue
        items.append(
            {
                "trx_id": m.trx_id,
                # Use moderation timestamp for ordering/pagination
                "timestamp": mod.mod_at.isoformat()
                if mod.mod_at
                else m.timestamp.isoformat(),
                "author": m.author,
                "content": m.content,
                "tags": json.loads(m.tags) if m.tags else [],
                "hidden": True,
                "pending": False,
                "approvals": None,
                "quorum": quorum,
                "mod_reason": mod.mod_reason if mod and mod.mod_reason else None,
            }
        )

    # 2) Pending items: latest hide approvals since last unhide, ordered by last action time
    act_q = ModerationAction.query.filter(ModerationAction.action == "hide")
    if cursor_dt is not None:
        act_q = act_q.filter(ModerationAction.created_at < cursor_dt)
    act_q = act_q.order_by(ModerationAction.created_at.desc()).limit(limit * 3)
    acts = act_q.all()
    seen_trx: set[str] = set()
    for a in acts:
        if a.trx_id in seen_trx:
            continue
        seen_trx.add(a.trx_id)
        # Skip if already hidden
        mod = Moderation.query.filter_by(trx_id=a.trx_id).first()
        if mod and mod.visibility == "hidden":
            continue
        # Compute approvals since last unhide
        last_unhide = (
            db.session.query(ModerationAction.created_at)
            .filter(
                ModerationAction.trx_id == a.trx_id,
                ModerationAction.action == "unhide",
            )
            .order_by(ModerationAction.created_at.desc())
            .first()
        )
        cutoff = last_unhide[0] if last_unhide else None
        approvals_q = db.session.query(ModerationAction.moderator).filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            approvals_q = approvals_q.filter(ModerationAction.created_at > cutoff)
        approvals = approvals_q.distinct().count()

        pending = (quorum > 1) and (approvals > 0) and (approvals < quorum)
        if not pending:
            continue

        # Get latest hide action time and reason after cutoff
        hide_actions_q = ModerationAction.query.filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            hide_actions_q = hide_actions_q.filter(ModerationAction.created_at > cutoff)
        latest_hide = hide_actions_q.order_by(
            ModerationAction.created_at.desc()
        ).first()

        m = Message.query.filter_by(trx_id=a.trx_id).first()
        if not m:
            continue
        items.append(
            {
                "trx_id": m.trx_id,
                # Use latest hide action time as moderation timestamp
                "timestamp": latest_hide.created_at.isoformat()
                if latest_hide
                else m.timestamp.isoformat(),
                "author": m.author,
                "content": m.content,
                "tags": json.loads(m.tags) if m.tags else [],
                "hidden": False,
                "pending": True,
                "approvals": int(approvals),
                "quorum": quorum,
                "mod_reason": None,
            }
        )

    # Apply status filter similar to public audit
    if status == "hidden":
        items = [it for it in items if it.get("hidden") is True]
    elif status == "pending":
        items = [it for it in items if it.get("pending") is True]
    else:
        items = [
            it
            for it in items
            if (it.get("hidden") or it.get("pending") or it.get("mod_reason"))
        ]

    # Final ordering by moderation timestamp
    def _pick_ts(x: dict) -> str:
        return x.get("timestamp") or ""

    items.sort(key=lambda it: _pick_ts(it), reverse=True)

    # Enforce limit
    items = items[:limit]

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
    session.permanent = True
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


# --- Moderator navbar pending notifications ---
@api_bp.route("/mod/pending_count")
def api_mod_pending_count():
    if "username" not in session:
        return jsonify({"count": 0}), 401
    uname = session["username"].lower()
    if uname not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"count": 0}), 403

    # Last seen marker for moderator
    state = ModerationState.query.get(uname)
    last_seen = state.last_seen if state and state.last_seen else None

    quorum = int(current_app.config.get("MOD_QUORUM", 1))
    count = 0

    # Consider items currently pending quorum
    # Strategy mirrors mod_audit/mod_list: latest hide approvals since last unhide
    act_q = (
        ModerationAction.query.filter(ModerationAction.action == "hide")
        .order_by(ModerationAction.created_at.desc())
        .limit(300)
    )
    acts = act_q.all()
    seen_trx = set()
    for a in acts:
        if a.trx_id in seen_trx:
            continue
        seen_trx.add(a.trx_id)
        # Skip if already hidden
        mod = Moderation.query.filter_by(trx_id=a.trx_id).first()
        if mod and mod.visibility == "hidden":
            continue
        # Determine cutoff at last unhide
        last_unhide = (
            db.session.query(ModerationAction.created_at)
            .filter(
                ModerationAction.trx_id == a.trx_id,
                ModerationAction.action == "unhide",
            )
            .order_by(ModerationAction.created_at.desc())
            .first()
        )
        cutoff = last_unhide[0] if last_unhide else None
        approvals_q = db.session.query(ModerationAction.moderator).filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            approvals_q = approvals_q.filter(ModerationAction.created_at > cutoff)
        approvals = approvals_q.distinct().count()
        pending = (quorum > 1) and (approvals > 0) and (approvals < quorum)
        if not pending:
            continue
        # Latest hide action time
        hide_actions_q = ModerationAction.query.filter(
            ModerationAction.trx_id == a.trx_id,
            ModerationAction.action == "hide",
        )
        if cutoff is not None:
            hide_actions_q = hide_actions_q.filter(ModerationAction.created_at > cutoff)
        latest_hide = hide_actions_q.order_by(
            ModerationAction.created_at.desc()
        ).first()
        latest_ts = latest_hide.created_at if latest_hide else a.created_at
        if last_seen is None or (latest_ts and latest_ts > last_seen):
            count += 1

    return jsonify({"count": int(count)})


@api_bp.route("/mod/seen", methods=["POST"])
def api_mod_seen():
    if "username" not in session:
        return jsonify({"success": False}), 401
    uname = session["username"].lower()
    if uname not in (current_app.config.get("MODERATORS") or []):
        return jsonify({"success": False}), 403
    now = _utcnow_naive()
    state = ModerationState.query.get(uname)
    if state is None:
        state = ModerationState(username=uname, last_seen=now)
        db.session.add(state)
    else:
        state.last_seen = now
    db.session.commit()
    return jsonify({"success": True, "last_seen": now.isoformat()})
