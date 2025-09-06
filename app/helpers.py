import json
import os
import threading
import time
from datetime import datetime, timezone

from bleach import clean, linkify
from flask import current_app, jsonify, request
from markdown import markdown
from nectar.account import Account
from nectar.hive import Hive
from nectargraphenebase.account import PublicKey
from nectargraphenebase.ecdsasig import verify_message

from .extensions import cache
from .models import Category, Checkpoint, Message, Post, Topic, TopicAction, db


def _utcnow_naive() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize any datetime to naive UTC for consistent DB storage."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def markdown_render(content: str) -> str:
    """Render user content as sanitized HTML (minimal subset).
    - Convert simple @mentions and #tags to links before Markdown.
    - Render with Python-Markdown using minimal features (no tables/fences/admonitions).
    - Sanitize with Bleach allowing only basic inline formatting, links, images,
      code (inline/pre), and blockquotes. No headings, lists, tables, or complex blocks.
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

        # Render Markdown with minimal extensions
        # We avoid 'extra' (tables/fenced code), 'admonition', and other heavy features.
        html = markdown(
            txt,
            extensions=[
                "fenced_code",
                "codehilite",  # syntax highlighting via Pygments
            ],
            extension_configs={
                "codehilite": {
                    "guess_lang": True,
                    "noclasses": False,  # prefer CSS classes for theming
                    "pygments_style": "default",
                    "css_class": "codehilite",
                    "wrapcode": True,
                },
            },
            output_format="html5",
        )
        # Sanitize HTML
        allowed_tags = {
            "p",
            "br",
            "em",
            "strong",
            "code",
            "pre",
            "blockquote",
            "a",
            "img",
            "div",  # for codehilite wrapper
            "span",  # for pygments token spans
        }
        allowed_attrs = {
            "a": ["href", "title", "rel", "target"],
            "code": ["class"],
            # Disallow width/height overrides; keep loading for lazy images
            "img": ["src", "alt", "title", "loading"],
            "div": ["class"],
            "span": ["class"],
            "pre": ["class"],
        }
        allowed_protocols = ["http", "https", "mailto"]
        safe = clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True,
        )
        # Auto-link bare URLs safely, but skip entire code blocks to preserve structure
        try:
            import re as _re_link

            def _linkify_segment(segment: str) -> str:
                try:
                    return linkify(segment)
                except Exception:
                    return segment

            # Match either a full codehilite wrapper or a standalone <pre> block
            code_pattern = _re_link.compile(
                r"(<div[^>]*class=\"[^\"]*codehilite[^\"]*\"[^>]*>[\s\S]*?<\/div>|<pre[\s\S]*?>[\s\S]*?<\/pre>)",
                _re_link.IGNORECASE,
            )
            tokens = code_pattern.split(safe)
            # tokens alternates: [non-code, code, non-code, code, ...]
            for i in range(0, len(tokens)):
                if i % 2 == 0:  # non-code segment
                    tokens[i] = _linkify_segment(tokens[i])
            safe = "".join(tokens)
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

        # Enforce rel on all anchors for safety
        try:
            import re as _re2

            def _add_rel(m):
                tag_open = m.group(0)
                # If rel already present, leave as-is; otherwise add safe defaults
                if " rel=" in tag_open:
                    return tag_open
                return tag_open[:-1] + ' rel="nofollow noopener noreferrer">'

            safe = _re2.sub(r"<a\b(?![^>]*\brel=)[^>]*>", _add_rel, safe)
        except Exception:
            pass
        return safe
    except Exception:
        # Fallback: escape everything via bleach
        try:
            return clean(str(content or ""), strip=True)
        except Exception:
            return ""


def _get_hive_instance():
    """Return a Hive instance (uses shared instance if configured)."""
    try:
        return Hive(node=current_app.config["HIVE_NODES"])
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
        current_app.logger.info(
            "[following] fetching for user=%s via nectar.Account.get_following()", uname
        )
    except Exception:
        pass
    try:
        acct = Account(uname)
        resp = acct.get_following()  # library-provided helper
    except Exception as e:
        try:
            current_app.logger.warning(
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
        current_app.logger.info(
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
        parsed = datetime.fromisoformat(ts)
        return _to_naive_utc(parsed)
    except Exception:
        # Fallback to UTC (naive)
        return _utcnow_naive()


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
    dt = _parse_timestamp(ts) if isinstance(ts, str) else _utcnow_naive()
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
                # Check for both microblog and forum APP_IDs
                payload_id = payload.get("id")
                micro_app_id = current_app.config["APP_ID"]
                forum_app_id = current_app.config.get("FORUM_APP_ID", "hive.forum")

                if payload_id not in [micro_app_id, forum_app_id]:
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
                # Handle different operation types
                op_type = body.get("type")
                trx_id = tx.get("transaction_id") or f"{block_num}-{tx_idx}-{op_idx}"

                # Route to appropriate processor based on APP_ID
                if payload_id == forum_app_id and op_type == "topic":
                    # Forum topic creation
                    title = body.get("title", "").strip()
                    content = body.get("content", "").strip()
                    if not title or not content:
                        continue

                    # Get or create category
                    category_slug = body.get("category", "general")
                    category = Category.query.filter_by(
                        slug=category_slug, is_active=True
                    ).first()
                    if not category:
                        # Auto-create category with reasonable defaults
                        if category_slug == "general":
                            category = Category(
                                slug="general",
                                name="General Discussion",
                                description="General topics and discussions",
                                created_by=author,
                                sort_order=0,
                            )
                        else:
                            # Auto-create other categories with generated names
                            category_name = category_slug.replace("-", " ").title()
                            category = Category(
                                slug=category_slug,
                                name=category_name,
                                description=f"Discussions about {category_name.lower()}",
                                created_by=author,
                                sort_order=99,  # New categories go to the end
                            )
                        db.session.add(category)
                        db.session.flush()  # Get the ID

                    # Extract mentions/tags
                    mentions = body.get("mentions") or []
                    tags = body.get("tags") or []
                    if not mentions or not tags:
                        em, et = _extract_mentions_tags(f"{title} {content}")
                        if not mentions:
                            mentions = em
                        if not tags:
                            tags = et

                    # Upsert topic
                    if not Topic.query.filter_by(trx_id=trx_id).first():
                        topic = Topic(
                            trx_id=trx_id,
                            block_num=block_num,
                            timestamp=dt,
                            title=title[:200],  # Enforce length limit
                            content=content,
                            author=author,
                            category_id=category.id,
                            tags=json.dumps(tags) if tags else None,
                            mentions=json.dumps(mentions) if mentions else None,
                            last_activity=dt,
                            last_author=author,
                            raw_json=json.dumps(body),
                        )
                        db.session.add(topic)
                        inserted += 1

                elif payload_id == forum_app_id and op_type == "post":
                    # Forum post/reply
                    content = body.get("content", "").strip()
                    topic_id_trx = body.get("topic_id")
                    if not content or not topic_id_trx:
                        continue

                    # Find the topic being replied to
                    topic = Topic.query.filter_by(trx_id=topic_id_trx).first()
                    if not topic or topic.is_locked:
                        continue

                    # Extract mentions
                    mentions = body.get("mentions") or []
                    if not mentions:
                        mentions = _extract_mentions_tags(content)[0]

                    # Find reply-to post if specified
                    reply_to_trx = body.get("reply_to")
                    reply_to_post = None
                    if reply_to_trx:
                        reply_to_post = Post.query.filter_by(
                            trx_id=reply_to_trx, topic_id=topic.id
                        ).first()

                    # Upsert post
                    if not Post.query.filter_by(trx_id=trx_id).first():
                        post = Post(
                            trx_id=trx_id,
                            block_num=block_num,
                            timestamp=dt,
                            content=content,
                            author=author,
                            topic_id=topic.id,
                            reply_to_id=reply_to_post.id if reply_to_post else None,
                            mentions=json.dumps(mentions) if mentions else None,
                            raw_json=json.dumps(body),
                        )
                        db.session.add(post)

                        # Update topic stats
                        topic.reply_count = (
                            Post.query.filter_by(topic_id=topic.id).count() + 1
                        )
                        topic.last_activity = dt
                        topic.last_author = author

                        inserted += 1

                elif payload_id == forum_app_id and op_type == "topic_action":
                    # Topic administrative actions (moderator only)
                    topic_id_trx = body.get("topic_id")
                    action = body.get("action")
                    if not topic_id_trx or not action:
                        continue

                    # Check if user is moderator
                    if author.lower() not in current_app.config.get("MODERATORS", []):
                        continue

                    topic = Topic.query.filter_by(trx_id=topic_id_trx).first()
                    if not topic:
                        continue

                    # Apply the action
                    if action == "lock":
                        topic.is_locked = True
                    elif action == "unlock":
                        topic.is_locked = False
                    elif action == "pin":
                        topic.is_pinned = True
                    elif action == "unpin":
                        topic.is_pinned = False
                    elif action == "hide":
                        topic.is_hidden = True
                    elif action == "unhide":
                        topic.is_hidden = False
                    elif action == "move":
                        new_category_slug = body.get("category")
                        if new_category_slug:
                            new_category = Category.query.filter_by(
                                slug=new_category_slug, is_active=True
                            ).first()
                            if new_category:
                                topic.category_id = new_category.id

                    # Log the action
                    action_log = TopicAction(
                        topic_id=topic.id,
                        moderator=author,
                        action=action,
                        reason=body.get("reason"),
                        timestamp=dt,
                        action_data=json.dumps(
                            {
                                k: v
                                for k, v in body.items()
                                if k not in ["app", "v", "type"]
                            }
                        ),
                    )
                    db.session.add(action_log)
                    inserted += 1

                elif payload_id == forum_app_id and op_type == "category_action":
                    # Category management (admin only)
                    # For now, skip - can be implemented later for full admin functionality
                    continue

                else:
                    # Handle legacy microblog posts for backward compatibility
                    if op_type == "post" or op_type is None:  # Legacy format
                        content = body.get("content", "").strip()
                        if not content:
                            continue

                        mentions = body.get("mentions") or []
                        tags = body.get("tags") or []
                        if not mentions or not tags:
                            em, et = _extract_mentions_tags(content)
                            if not mentions:
                                mentions = em
                            if not tags:
                                tags = et
                        reply_to = body.get("reply_to")

                        # Only create legacy Message if not already exists
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


def _watcher_loop(app, stop_event: threading.Event, poll_interval: float = 1.0):
    """Background watcher loop that ingests blocks.

    Accepts a Flask `app` instance to create an application context inside
    the thread. This avoids relying on an imported global like `main.app`.
    """
    hv = _get_hive_instance()
    with app.app_context():
        from .models import db

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
_watcher_thread = None


def start_block_watcher(app=None):
    """Start the background block watcher thread.

    If `app` is not provided, attempt to resolve the real Flask app instance
    from `current_app`.
    """
    if os.environ.get("HIVE_MICRO_WATCHER", "1") != "1":
        return
    if app is None:
        try:
            # Resolve the underlying Flask app from the LocalProxy
            app = current_app._get_current_object()
        except Exception:
            return
    global _watcher_thread
    # Ensure the stop flag is cleared before starting
    try:
        _watcher_stop_event.clear()
    except Exception:
        pass
    if _watcher_thread is not None and _watcher_thread.is_alive():
        return
    _watcher_thread = threading.Thread(
        target=_watcher_loop, args=(app, _watcher_stop_event), daemon=True
    )
    _watcher_thread.start()


_initialized = False


def _ensure_initialized(app=None):
    global _initialized
    if _initialized:
        return
    # Prefer the provided app; otherwise use current_app
    ctx_app = app
    if ctx_app is None:
        try:
            ctx_app = current_app._get_current_object()
        except Exception:
            return
    with ctx_app.app_context():
        db.create_all()
    start_block_watcher(ctx_app)
    _initialized = True


def stop_block_watcher(timeout: float = 2.0):
    """Signal the watcher to stop and wait briefly for it to exit."""
    global _watcher_thread
    try:
        _watcher_stop_event.set()
        if _watcher_thread is not None and _watcher_thread.is_alive():
            _watcher_thread.join(timeout=timeout)
    except Exception:
        pass


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
