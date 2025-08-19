import json
import os
import threading
import time
from datetime import datetime, timezone

from bleach import clean, linkify
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_caching import Cache
from flask_sqlalchemy import SQLAlchemy
from markdown import markdown
from nectar.account import Account
from nectar.hive import Hive
from nectar.instance import set_shared_hive_instance
from nectargraphenebase.account import PublicKey
from nectargraphenebase.ecdsasig import verify_message

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

db = SQLAlchemy(app)
cache = Cache(app)
APP_ID = os.environ.get("HIVE_MICRO_APP_ID", "hive.micro")
_initialized = False

# Initialize Hive instance with optional custom nodes
nodes_env = os.environ.get("HIVE_NODES", "").strip()
if nodes_env:
    nodes = [n.strip() for n in nodes_env.split(",") if n.strip()]
    hv = Hive(node=nodes, num_retries=5, num_retries_call=3, timeout=15)
    set_shared_hive_instance(hv)


def markdown_render(content: str) -> str:
    """Render user content as sanitized HTML.
    - Convert simple @mentions and #tags to links before Markdown.
    - Render with Python-Markdown.
    - Sanitize with Bleach allowing a safe subset of tags/attrs.
    """
    try:
        txt = content or ""
        # Pre-linkify mentions/tags using Markdown link syntax to preserve formatting
        import re

        def _mention_sub(m):
            u = (m.group(2) or "").lower()
            return f"{m.group(1)}[@{u}](/u/{u})"

        def _tag_sub(m):
            t = (m.group(2) or "").lower()
            return f"{m.group(1)}[#{t}](/feed?tag={t})"

        txt = re.sub(r"(^|\s)@([a-z0-9\-.]+)", _mention_sub, txt)
        txt = re.sub(r"(^|\s)#([a-z0-9\-]+)", _tag_sub, txt)

        # Render Markdown with common extensions
        html = markdown(
            txt,
            extensions=[
                "extra",  # tables, fenced_code, etc.
                "sane_lists",
                "admonition",
                "codehilite",  # syntax highlighting via Pygments
            ],
            extension_configs={
                "codehilite": {
                    "guess_lang": False,
                    "noclasses": False,  # prefer CSS classes for theming
                    "pygments_style": "default",
                },
            },
            output_format="html5",
        )
        # Sanitize HTML
        allowed_tags = {
            "p",
            "br",
            "pre",
            "code",
            "blockquote",
            "em",
            "strong",
            "del",
            "hr",
            "ul",
            "ol",
            "li",
            "a",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "div",
            "span",
            "sup",
            "abbr",
            "dl",
            "dt",
            "dd",
            "table",
            "thead",
            "tbody",
            "caption",
            "tr",
            "th",
            "td",
            "img",
        }
        allowed_attrs = {
            "a": ["href", "title", "rel", "target", "id", "name"],
            "code": ["class"],
            "div": ["class"],
            "span": ["class", "id"],
            "li": ["id"],
            "sup": ["id"],
            "abbr": ["title"],
            "th": ["colspan", "rowspan", "align"],
            "td": ["colspan", "rowspan", "align"],
            "img": ["src", "alt", "title", "width", "height", "loading"],
        }
        allowed_protocols = ["http", "https", "mailto"]
        safe = clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True,
        )
        # Auto-link bare URLs safely
        try:
            safe = linkify(safe)
        except Exception:
            pass

        # Ensure images are lazy-loaded by default
        try:
            import re as _re

            safe = _re.sub(
                r"<img(?![^>]*\bloading=)([^>]*)>", r'<img loading="lazy"\1>', safe
            )
        except Exception:
            pass
        return safe
    except Exception:
        # Fallback: escape everything via bleach
        try:
            return clean(str(content or ""), strip=True)
        except Exception:
            return ""


@app.route("/api/v1/tags/trending")
def api_tags_trending():
    """Return trending tags from recent messages.
    Query params:
    - window: number of most recent rows to scan (default 500)
    - limit: maximum number of tags to return (default 10)
    """
    try:
        window = max(50, min(int(request.args.get("window", 500)), 5000))
    except Exception:
        window = 500
    try:
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
    except Exception:
        limit = 10

    # Get recent messages by timestamp desc limited to `window`
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

    # Sort by count desc then tag asc for stability
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    items = [{"tag": k, "count": v} for k, v in top]
    return jsonify({"items": items, "count": len(items)})

# --- Models ---
class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    trx_id = db.Column(db.String(64), unique=True, nullable=False)
    block_num = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)
    author = db.Column(db.String(32), index=True, nullable=False)
    type = db.Column(db.String(16), nullable=False, default="post")
    content = db.Column(db.Text, nullable=False)
    mentions = db.Column(db.Text, nullable=True)  # JSON string
    tags = db.Column(db.Text, nullable=True)  # JSON string
    reply_to = db.Column(db.String(64), nullable=True)
    raw_json = db.Column(db.Text, nullable=True)


class Checkpoint(db.Model):
    __tablename__ = "checkpoints"
    id = db.Column(db.Integer, primary_key=True)
    last_block = db.Column(db.Integer, nullable=False, default=0)


class MentionState(db.Model):
    __tablename__ = "mention_state"
    username = db.Column(db.String(32), primary_key=True)
    last_seen = db.Column(db.DateTime, nullable=True, index=True)


# --- Block watcher using Nectar RPC ---
def _get_hive_instance():
    """Return a Hive instance (uses shared instance if configured)."""
    try:
        return Hive()
    except Exception:
        # Fallback: reuse earlier hv if available via shared instance
        return Hive()


def _get_head_block_num(hv: Hive) -> int:
    props = hv.rpc.get_dynamic_global_properties()
    # head_block_number or last_irreversible_block_num may be present
    return props.get("head_block_number") or props.get("last_irreversible_block_num")


def _get_following_usernames(username: str) -> set[str]:
    """Fetch following set from chain using condenser API and cache it briefly.
    Username normalization is important: Hive accounts are lowercase.
    """
    uname = (username or "").strip().lower()
    cache_key = f"following:{uname}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    following: set[str] = set()
    try:
        app.logger.info(
            "[following] fetching for user=%s via nectar.Account.get_following()", uname
        )
    except Exception:
        pass
    try:
        acct = Account(uname)
        resp = acct.get_following()  # library-provided helper
    except Exception as e:
        try:
            app.logger.warning(
                "[following] nectar Account.get_following error for user=%s: %s",
                uname,
                e,
            )
        except Exception:
            pass
        resp = []

    # Normalize response to a lowercase set of usernames
    try:
        for entry in resp or []:
            if isinstance(entry, str):
                following.add(entry.strip().lower())
            elif isinstance(entry, dict):
                val = (
                    entry.get("following") or entry.get("name") or entry.get("account")
                )
                if val:
                    following.add(str(val).strip().lower())
            else:
                following.add(str(entry).strip().lower())
    except Exception:
        # Best-effort; leave following as-is
        pass
    try:
        app.logger.info(
            "[following] fetched count=%d for user=%s", len(following), uname
        )
    except Exception:
        pass
    cache.set(cache_key, following, timeout=60)
    return following


def _parse_timestamp(ts: str) -> datetime:
    # Handle "2025-08-18T15:30:00" or with trailing 'Z'
    if ts.endswith("Z"):
        ts = ts[:-1]
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        # As a fallback, return current time to avoid crashes
        return datetime.now(timezone.utc)


def _extract_mentions_tags(content: str) -> tuple[list[str], list[str]]:
    """Extract @mentions and #tags from content.
    Usernames: lowercase letters, digits, hyphen; start with @ and a letter/digit
    Tags: words after # with letters/digits/underscore/hyphen, up to 32 chars
    """
    try:
        import re

        # Hive usernames: 3-16 chars, but we capture liberally then normalize
        mention_pat = re.compile(r"@([a-z0-9][a-z0-9\-\.]{1,31})")
        tag_pat = re.compile(r"#([a-z0-9_\-]{1,32})")
        mentions = {m.lower().strip("-.") for m in mention_pat.findall(content.lower())}
        tags = {t.lower().strip("-_") for t in tag_pat.findall(content.lower())}
        # Basic sanity filters
        mentions = {m for m in mentions if 2 <= len(m) <= 32}
        tags = {t for t in tags if 1 <= len(t) <= 32}
        return sorted(mentions), sorted(tags)
    except Exception:
        return [], []


def _ingest_block(hv: Hive, block_num: int):
    blk = hv.rpc.get_block(block_num)
    if not blk:
        return 0
    ts = blk.get("timestamp")
    dt = _parse_timestamp(ts) if isinstance(ts, str) else datetime.now(timezone.utc)
    txs = blk.get("transactions", [])
    inserted = 0
    for tx_idx, tx in enumerate(txs):
        # Operations are typically [[op_type, op_payload], ...]
        ops = tx.get("operations", [])
        for op_idx, op in enumerate(ops):
            try:
                if not isinstance(op, (list, tuple)) or len(op) != 2:
                    continue
                op_type, payload = op
                if op_type != "custom_json":
                    continue
                if payload.get("id") != APP_ID:
                    continue
                # Determine author from required posting auths
                rpa = payload.get("required_posting_auths", []) or []
                ra = payload.get("required_auths", []) or []
                author = rpa[0] if rpa else (ra[0] if ra else None)
                if not author:
                    continue
                # Parse json payload (string or dict)
                body = payload.get("json")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        continue
                if not isinstance(body, dict):
                    continue
                if body.get("type") != "post":
                    # v1 implements only posts; ignore others
                    continue
                content = body.get("content", "").strip()
                if not content:
                    continue
                # Mentions/tags: derive from content when not provided
                mentions = body.get("mentions") or []
                tags = body.get("tags") or []
                if not mentions or not tags:
                    em, et = _extract_mentions_tags(content)
                    if not mentions:
                        mentions = em
                    if not tags:
                        tags = et
                reply_to = body.get("reply_to")
                # trx_id may not be present on tx; generate stable fallback
                trx_id = tx.get("transaction_id") or f"{block_num}-{tx_idx}-{op_idx}"

                # Upsert by trx_id
                if not Message.query.filter_by(trx_id=trx_id).first():
                    m = Message(
                        trx_id=trx_id,
                        block_num=block_num,
                        timestamp=dt,
                        author=author,
                        type="post",
                        content=content,
                        mentions=json.dumps(mentions) if mentions else None,
                        tags=json.dumps(tags) if tags else None,
                        reply_to=reply_to,
                        raw_json=json.dumps(body),
                    )
                    db.session.add(m)
                    inserted += 1
            except Exception:
                # Skip malformed ops but continue
                continue
    if inserted:
        db.session.commit()
    return inserted


def _watcher_loop(stop_event: threading.Event, poll_interval: float = 1.0):
    hv = _get_hive_instance()
    with app.app_context():
        # Ensure tables exist
        db.create_all()
        # Get or create checkpoint row with id=1
        ck = Checkpoint.query.get(1)
        if ck is None:
            ck = Checkpoint(id=1, last_block=0)
            db.session.add(ck)
            db.session.commit()
        while not stop_event.is_set():
            try:
                head = _get_head_block_num(hv) or 0
                next_block = (
                    ck.last_block + 1
                    if ck.last_block
                    else (head - 20 if head > 20 else 1)
                )
                if next_block > head:
                    # up-to-date; sleep
                    time.sleep(poll_interval)
                    continue
                # Process a small batch to avoid long transactions
                batch_end = min(head, next_block + 50)
                for bn in range(next_block, batch_end + 1):
                    _ingest_block(hv, bn)
                    ck.last_block = bn
                db.session.commit()
            except Exception:
                # Backoff on errors
                time.sleep(2.0)
            finally:
                # brief pause between batches
                time.sleep(0.05)


_watcher_stop_event = threading.Event()


def start_block_watcher():
    if os.environ.get("HIVE_MICRO_WATCHER", "1") != "1":
        return
    t = threading.Thread(target=_watcher_loop, args=(_watcher_stop_event,), daemon=True)
    t.start()


def _ensure_initialized():
    global _initialized
    if _initialized:
        return
    with app.app_context():
        db.create_all()
    start_block_watcher()
    _initialized = True


@app.before_request
def _before_request_init():
    _ensure_initialized()


def _parse_login_payload():
    """Parse and normalize login payload from JSON body.
    Accepts alternative keys often used by clients.
    Returns tuple (signature_hex, username, pubkey, message, error_json_or_none, status_code).
    """
    data = request.get_json(silent=True) or {}
    # Normalize field names
    signature = data.get("challenge") or data.get("signature") or data.get("sig")
    username = data.get("username") or data.get("user")
    pubkey = data.get("pubkey") or data.get("public_key") or data.get("key")
    message = data.get("proof") or data.get("message") or data.get("msg")

    missing = [
        k
        for k, v in {
            "signature": signature,
            "username": username,
            "pubkey": pubkey,
            "message": message,
        }.items()
        if v in (None, "")
    ]
    if missing:
        return (
            None,
            None,
            None,
            None,
            jsonify(
                {
                    "success": False,
                    "error": "Missing required fields",
                    "missing": missing,
                    "received_keys": list(data.keys()),
                }
            ),
            400,
        )

    # Clean signature (strip optional 0x)
    if isinstance(signature, str) and signature.startswith("0x"):
        signature = signature[2:]

    return signature, username, pubkey, message, None, 200


def _verify_signature_and_key(
    username: str, pubkey: str, message: str, signature_hex: str
):
    """Verify signature and ensure pubkey belongs to account."""
    # Fetch posting public keys from blockchain
    # Use shared Hive instance; do not pass nectar.blockchain.Blockchain wrapper here
    account = Account(username)
    posting = account.get("posting")
    if isinstance(posting, dict) and "key_auths" in posting:
        posting_keys = [
            auth[0] if isinstance(auth, (list, tuple)) else auth.get("key")
            for auth in posting["key_auths"]
        ]
    elif isinstance(posting, list):
        posting_keys = posting
    else:
        raise ValueError(f"Unexpected posting structure: {type(posting)} {posting}")

    if pubkey not in posting_keys:
        return False, {
            "success": False,
            "error": "Provided public key is not a valid posting key for this account.",
            "account": username,
            "pubkey": pubkey,
        }

    # Verify signature recovers same pubkey
    # Signature may be hex or base64; try hex first, then base64 as fallback
    sig_bytes = None
    try:
        sig_bytes = bytes.fromhex(signature_hex)
    except Exception:
        try:
            import base64

            sig_bytes = base64.b64decode(signature_hex)
        except Exception:
            raise ValueError("Signature is neither valid hex nor base64")

    recovered_pubkey_bytes = verify_message(message, sig_bytes)
    recovered_pubkey_str = str(PublicKey(recovered_pubkey_bytes.hex(), prefix="STM"))
    return recovered_pubkey_str == pubkey, {
        "success": False,
        "error": "Signature is invalid.",
    }


# --- API: Local timeline backed by DB ---
@app.route("/api/v1/timeline")
def api_timeline():
    """Return micro-posts from local DB. Optional params:
    - limit: int (default 20, max 100)
    - cursor: ISO8601 timestamp to paginate before
    - following: 1 to filter by authors the logged-in user follows (planned)
    """
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 100))

    cursor = request.args.get("cursor")
    following_flag = request.args.get("following", "0") == "1"
    tag_filter = request.args.get("tag")

    # Debug: log request parameters and user
    try:
        app.logger.info(
            "[timeline] params: following=%s tag=%s cursor=%s user=%s",
            following_flag,
            tag_filter,
            cursor,
            session.get("username"),
        )
    except Exception:
        pass

    q = Message.query
    if cursor:
        try:
            dt = datetime.fromisoformat(cursor)
            q = q.filter(Message.timestamp < dt)
        except Exception:
            pass

    # Filter by on-chain following when requested and logged in
    if following_flag and session.get("username"):
        flw = _get_following_usernames(session["username"]) or set()
        try:
            app.logger.info(
                "[timeline] following filter enabled; user=%s following_count=%d",
                session.get("username"),
                len(flw),
            )
        except Exception:
            pass
        if flw:
            q = q.filter(Message.author.in_(list(flw)))
        else:
            # No following; return empty set quickly
            q = q.filter(db.text("0"))
    elif following_flag and not session.get("username"):
        try:
            app.logger.warning(
                "[timeline] following=1 but no logged-in user; skipping filter"
            )
        except Exception:
            pass

    # Filter by tag if provided (simple LIKE over JSON array string)
    if tag_filter:
        like_pattern = f'%"{tag_filter.lower()}"%'
        q = q.filter(Message.tags.like(like_pattern))

    # Order and limit
    q = q.order_by(Message.timestamp.desc()).limit(limit)

    items = []
    posts = q.all()
    try:
        app.logger.info("[timeline] result_count=%d", len(posts))
    except Exception:
        pass
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


# --- API: New posts count since timestamp ---
@app.route("/api/v1/timeline/new_count")
def api_timeline_new_count():
    """Return count of posts newer than 'since' timestamp.
    Query params:
    - since: ISO8601 timestamp (required)
    - following: '1' to restrict to authors the logged-in user follows
    - tag: filter to posts containing a given tag
    """
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
    elif following_flag and not session.get("username"):
        # No user -> no following filter
        pass

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


# --- API: Single post and its replies ---
@app.route("/api/v1/post/<trx_id>")
def api_post(trx_id: str):
    """Return a single post by trx_id and its replies."""
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
    # Replies referencing this trx_id
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


@app.route("/api/v1/mentions/count")
def api_mentions_count():
    """Return count of posts that mention the logged-in user."""
    if "username" not in session:
        return jsonify({"count": 0}), 401
    uname = session["username"].lower()
    like_pattern = f'%"{uname}"%'
    q = Message.query.filter(Message.mentions.like(like_pattern))
    # Unread since last_seen
    state = MentionState.query.get(uname)
    if state and state.last_seen:
        q = q.filter(Message.timestamp > state.last_seen)
    cnt = q.count()
    return jsonify({"count": cnt})


@app.route("/api/v1/mentions/seen", methods=["POST"])
def api_mentions_seen():
    """Mark mentions as seen at current time for the logged-in user."""
    if "username" not in session:
        return jsonify({"success": False}), 401
    uname = session["username"].lower()
    now = datetime.now(timezone.utc)
    state = MentionState.query.get(uname)
    if state is None:
        state = MentionState(username=uname, last_seen=now)
        db.session.add(state)
    else:
        state.last_seen = now
    db.session.commit()
    return jsonify({"success": True, "last_seen": now.isoformat()})


@app.route("/api/v1/status")
def api_status():
    """Return simple ingest status and counts."""
    _ensure_initialized()
    total = Message.query.count()
    ck = Checkpoint.query.get(1)
    return jsonify(
        {
            "messages": total,
            "last_block": ck.last_block if ck else 0,
            "app_id": APP_ID,
        }
    )


@app.route("/api/v1/mentions")
def api_mentions():
    """Return posts that mention the logged-in user. Optional params:
    - limit: int (default 20, max 100)
    - cursor: ISO8601 timestamp to paginate before
    """
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

    # SQLite-compatible search for the username in mentions JSON
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


@app.route("/login", methods=["POST"])
def login():
    """
    Accepts a POST request with a Hive Keychain signature and verifies it.
    Expects JSON with: challenge (signature), username, pubkey, proof (message).
    Returns a session token if successful.
    """
    signature, username, pubkey, message, err, status = _parse_login_payload()
    if err is not None:
        return err, status

    # Fetch posting public keys from blockchain
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

    # Success: store username in session
    session["username"] = username
    return jsonify({"success": True, "username": username})


@app.route("/api/v1/login", methods=["POST"])
def api_login():
    # Simple alias for compatibility with test pages/tools
    return login()


@app.route("/")
def index():
    """Render the login page or redirect to feed if logged in."""
    if "username" in session:
        return redirect(url_for("feed"))
    return render_template("login.html")


@app.route("/feed")
def feed():
    """Render the feed page."""
    if "username" not in session:
        return redirect(url_for("index"))
    # Client-side will fetch from /api/v1/timeline
    return render_template("feed.html")


@app.route("/mentions")
def mentions_page():
    if "username" not in session:
        return redirect(url_for("index"))
    return render_template("mentions.html")


@app.route("/new_post")
def new_post():
    """Render the new post page."""
    if "username" not in session:
        return redirect(url_for("index"))
    return render_template("new_post.html")


@app.route("/profile")
def profile():
    """Render the profile page."""
    if "username" not in session:
        return redirect(url_for("index"))
    username = session["username"]
    account = Account(username)
    # Prefer posting_json_metadata; fall back to json_metadata
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
        "profile.html",
        username=username,
        profile=profile,
        raw=meta,
    )


@app.route("/u/<username>")
def public_profile(username: str):
    """Public profile page for any Hive user."""
    uname = (username or "").strip()
    if not uname:
        return redirect(url_for("feed"))
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
    return render_template("user_profile.html", username=uname, profile=prof, raw=meta)


@app.route("/p/<trx_id>")
def post_page(trx_id: str):
    """Public permalink page for a single post and its replies."""
    if not trx_id:
        return redirect(url_for("index"))
    return render_template("post.html", trx_id=trx_id)


@app.route("/logout")
def logout():
    """Log the user out."""
    session.pop("username", None)
    return redirect(url_for("index"))


if __name__ == "__main__":
    # Only run the Flask app if this script is executed directly
    with app.app_context():
        db.create_all()
    # Start background watcher
    start_block_watcher()
    app.run(debug=True, port=8000)


# --- Error handlers ---
@app.errorhandler(401)
def handle_401(error):
    return render_template("401.html"), 401


@app.errorhandler(403)
def handle_403(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def handle_404(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def handle_500(error):
    return render_template("500.html"), 500


# Optional: simple routes to preview error pages (guarded by env var)
if os.environ.get("ENABLE_ERROR_ROUTES", "1") == "1":

    @app.route("/error/401")
    def _error_401():
        abort(401)

    @app.route("/error/403")
    def _error_403():
        abort(403)

    @app.route("/error/404")
    def _error_404():
        abort(404)

    @app.route("/error/500")
    def _error_500():
        # raise an exception to trigger 500 handler
        raise RuntimeError("Test 500 error page")
