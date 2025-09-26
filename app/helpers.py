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
from nectar.block import Blocks
from nectargraphenebase.account import PublicKey
from nectargraphenebase.ecdsasig import verify_message

from .extensions import cache
from .models import Checkpoint, Message, db


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
        # Replace valid YouTube links with a lightweight preview block (feature-flagged)
        try:
            from flask import current_app as _curr_app

            if not (_curr_app and _curr_app.config.get("YOUTUBE_PREVIEW", False)):
                # Feature disabled: return sanitized HTML as-is
                return safe
            import re as _reyt
            from urllib.parse import urlparse, parse_qs

            VALID_HOSTS = {
                "www.youtube.com",
                "youtube.com",
                "m.youtube.com",
                "youtu.be",
            }

            def _extract_vid(url: str) -> str | None:
                try:
                    p = urlparse(url)
                    if p.netloc not in VALID_HOSTS:
                        return None
                    vid = None
                    if p.netloc == "youtu.be":
                        vid = p.path.lstrip("/")
                    elif p.path.startswith("/shorts/"):
                        parts = p.path.split("/")
                        vid = parts[2] if len(parts) > 2 else None
                    elif p.path.startswith("/embed/"):
                        parts = p.path.split("/")
                        vid = parts[2] if len(parts) > 2 else None
                    else:
                        q = parse_qs(p.query)
                        vid = (q.get("v") or [None])[0]
                    if vid and _reyt.match(r"^[a-zA-Z0-9_-]{11}$", vid):
                        return vid
                    return None
                except Exception:
                    return None

            def _preview_html(video_id: str) -> str:
                thumb = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                embed = f"https://www.youtube.com/embed/{video_id}?autoplay=1"
                return (
                    '<div class="youtubePreview" role="button" tabindex="0" '
                    f'data-video-url="{embed}">'  # handled by JS click listener
                    "<div>"
                    f'<img class="youtubeThumbnail" src="{thumb}" alt="YouTube video thumbnail" loading="lazy" />'
                    "</div>"
                    '<div class="playButton">'
                    '<svg class="playIcon" width="68" height="48" viewBox="0 0 68 48" aria-hidden="true">'
                    '<path d="M66.52,7.74c-0.78-2.93-2.49-5.41-5.42-6.19C55.79,.13,34,0,34,0S12.21,.13,6.9,1.55 C3.97,2.33,2.27,4.81,1.48,7.74C0.06,13.05,0,24,0,24s0.06,10.95,1.48,16.26c0.78,2.93,2.49,5.41,5.42,6.19 C12.21,47.87,34,48,34,48s21.79-0.13,27.1-1.55c2.93-0.78,4.64-3.26,5.42-6.19C67.94,34.95,68,24,68,24S67.94,13.05,66.52,7.74z" fill="#f00"/>'
                    '<path d="M45,24 27,14 27,34" fill="#fff"/></svg>'
                    "</div>"
                    "</div>"
                )

            # Replace anchors that point to YouTube with preview markup
            def _replace_anchor(m):
                href = m.group(1)
                vid = _extract_vid(href)
                return _preview_html(vid) if vid else m.group(0)

            safe = _reyt.sub(
                r'<a\s+[^>]*href="([^"]+)"[^>]*>[^<]*<\/a>', _replace_anchor, safe
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


def _get_hive_instance():
    """Return a Hive instance (uses shared instance if configured)."""
    try:
        hv = Hive(node=current_app.config["HIVE_NODES"])
        try:
            current_app.logger.info(
                "[watcher] initialized Hive instance with custom nodes: %s",
                current_app.config.get("HIVE_NODES"),
            )
        except Exception:
            pass
        return hv
    except Exception:
        # Fallback: reuse earlier hv if available via shared instance
        try:
            current_app.logger.warning(
                "[watcher] failed to init Hive with custom nodes, falling back to default shared instance"
            )
        except Exception:
            pass
        return Hive()


def _get_head_block_num(hv: Hive) -> int:
    props = hv.rpc.get_dynamic_global_properties()
    # head_block_number or last_irreversible_block_num may be present
    return props.get("head_block_number") or props.get("last_irreversible_block_num")


def _ops_map_for_block(
    hv: Hive, bn: int, app_id: str
) -> tuple[dict[tuple[str, str], list[str]], list[str]]:
    """Return (map, order) for our app's custom_json ops in a block.
    - map: (author, content) -> [trx_ids]
    - order: [trx_ids] in the order ops were seen in the block (for index fallback)
    Tries get_ops_in_block first; if empty, falls back to full block fetch.
    Only real transaction hashes are included; items without a hash are skipped from map,
    but order preserves positional alignment with None placeholders.
    """
    mp: dict[tuple[str, str], list[str]] = {}
    order: list[str | None] = []
    try:
        raw_ops = hv.rpc.get_ops_in_block(bn, True) or []
        for ro in raw_ops:
            try:
                op_pair = ro.get("op") if isinstance(ro, dict) else None
                if not isinstance(op_pair, (list, tuple)) or len(op_pair) != 2:
                    continue
                t, pl = op_pair
                if t != "custom_json":
                    continue
                if isinstance(pl, str):
                    try:
                        pl = json.loads(pl)
                    except Exception:
                        pl = {}
                if not isinstance(pl, dict):
                    continue
                if pl.get("id") != app_id:
                    continue
                rpa = pl.get("required_posting_auths", []) or []
                ra = pl.get("required_auths", []) or []
                author = rpa[0] if rpa else (ra[0] if ra else None)
                if not author:
                    continue
                body = pl.get("json")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        body = None
                if not isinstance(body, dict) or body.get("type") != "post":
                    continue
                content = (body.get("content") or "").strip()
                if not content:
                    continue
                txh = None
                for k in ("transaction_id", "trx_id", "trxId"):
                    v = ro.get(k)
                    if v:
                        txh = str(v)
                        break
                # Only map when we have a real hash; always keep order (may be None)
                order.append(txh)
                if txh:
                    key = (str(author), content)
                    mp.setdefault(key, []).append(txh)
            except Exception:
                continue
    except Exception:
        # leave mp/order empty; fallback below
        mp = {}
        order = []

    if mp or order:
        # Filter out None placeholders from order; map already only contains real hashes
        return mp, [x for x in order if x]

    # Fallback: full block
    try:
        full_blk = hv.rpc.get_block(bn) or {}
        txs = full_blk.get("transactions", []) or []
        for tx in txs:
            try:
                txh = tx.get("transaction_id")
                ops = tx.get("operations", []) or []
                for op in ops:
                    try:
                        if not isinstance(op, (list, tuple)) or len(op) != 2:
                            continue
                        f_type, fp = op
                        if f_type != "custom_json":
                            continue
                        if not isinstance(fp, dict):
                            continue
                        if fp.get("id") != app_id:
                            continue
                        rpa = fp.get("required_posting_auths", []) or []
                        ra = fp.get("required_auths", []) or []
                        author = rpa[0] if rpa else (ra[0] if ra else None)
                        if not author:
                            continue
                        body = fp.get("json")
                        if isinstance(body, str):
                            try:
                                body = json.loads(body)
                            except Exception:
                                body = None
                        if not isinstance(body, dict) or body.get("type") != "post":
                            continue
                        content = (body.get("content") or "").strip()
                        if not content:
                            continue
                        order.append(txh)
                        if txh:
                            key = (str(author), content)
                            mp.setdefault(key, []).append(txh)
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass
    return mp, [x for x in order if x]


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


def _ingest_custom_json_op(
    block_num: int,
    dt: datetime,
    payload: dict,
    tx_idx: int,
    op_idx: int,
    trx_id_override: str | None = None,
    seen_ids: set[str] | None = None,
) -> int:
    """Ingest a single custom_json op for our app ID. Returns 1 if inserted, else 0.

    This mirrors the logic inside _ingest_block() so bulk and single-block paths stay consistent.
    """
    try:
        # Determine author from required posting auths
        rpa = payload.get("required_posting_auths", []) or []
        ra = payload.get("required_auths", []) or []
        author = rpa[0] if rpa else (ra[0] if ra else None)
        if not author:
            return 0

        # Parse json payload (string or dict)
        body = payload.get("json")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                return 0
        if not isinstance(body, dict):
            return 0
        if body.get("type") != "post":
            # v1 implements only posts; ignore others
            return 0

        content = body.get("content", "").strip()
        if not content:
            return 0

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

        # Prefer provided transaction id override when available (e.g., from full block)
        # Fallback to payload value; finally generate a stable synthetic id
        trx_id = (
            trx_id_override
            or payload.get("transaction_id")
            or f"{block_num}-{tx_idx}-{op_idx}"
        )
        # Require real transaction hash; skip synthetic fallback like "block-tx-op"
        try:
            import re as _re_syn

            if isinstance(trx_id, str) and _re_syn.fullmatch(r"\d+-\d+-\d+", trx_id):
                try:
                    current_app.logger.warning(
                        "[ingest] skipping synthetic trx_id=%s at block=%s (need real transaction hash)",
                        trx_id,
                        block_num,
                    )
                except Exception:
                    pass
                return 0
        except Exception:
            pass
        # Prevent duplicates within the same transaction/batch
        if seen_ids is not None and trx_id in seen_ids:
            return 0
        # Skip if already in DB
        if Message.query.filter_by(trx_id=trx_id).first():
            return 0
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
        if seen_ids is not None:
            seen_ids.add(trx_id)
        return 1
    except Exception as e:
        try:
            current_app.logger.exception(
                "[ingest] exception while ingesting custom_json op at block=%s tx=%s op=%s: %s",
                block_num,
                tx_idx,
                op_idx,
                e,
            )
        except Exception:
            pass
        return 0


def _ingest_block(hv: Hive, block_num: int):
    blk = hv.rpc.get_block(block_num)
    if not blk:
        return 0
    ts = blk.get("timestamp")
    dt = _parse_timestamp(ts) if isinstance(ts, str) else _utcnow_naive()
    txs = blk.get("transactions", [])
    inserted = 0
    seen_ids: set[str] = set()
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
                if payload.get("id") != current_app.config["APP_ID"]:
                    continue
                # Prefer the real transaction hash from the tx envelope when available
                tx_hash = tx.get("transaction_id")
                inserted += _ingest_custom_json_op(
                    block_num=block_num,
                    dt=dt,
                    payload=payload,
                    tx_idx=tx_idx,
                    op_idx=op_idx,
                    trx_id_override=tx_hash,
                    seen_ids=seen_ids,
                )
            except Exception:
                # Skip malformed ops but continue
                continue
    if inserted:
        try:
            current_app.logger.debug(
                "[ingest] block=%s inserted_ops=%s", block_num, inserted
            )
        except Exception:
            pass
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    return inserted


def _watcher_loop(app, stop_event: threading.Event, poll_interval: float = 3.0):
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
        try:
            current_app.logger.info(
                "[watcher] loop started (poll_interval=%.2fs)", poll_interval
            )
        except Exception:
            pass
        while not stop_event.is_set():
            try:
                head = _get_head_block_num(hv) or 0
                next_block = (
                    ck.last_block + 1
                    if ck.last_block
                    else (head - 20 if head > 20 else 1)
                )
                try:
                    current_app.logger.debug(
                        "[watcher] head=%s next=%s (delta=%s)",
                        head,
                        next_block,
                        max(0, head - next_block),
                    )
                except Exception:
                    pass
                if next_block > head:
                    # up-to-date; sleep
                    try:
                        sleep_single = current_app.config.get(
                            "WATCHER_SINGLE_SLEEP_SEC", 2.5
                        )
                        current_app.logger.debug(
                            "[watcher] up-to-date; sleeping %.2fs", sleep_single
                        )
                    except Exception:
                        pass
                    try:
                        sleep_single = current_app.config.get(
                            "WATCHER_SINGLE_SLEEP_SEC", 2.5
                        )
                    except Exception:
                        sleep_single = 2.5
                    time.sleep(sleep_single)
                    continue
                backlog = max(0, head - next_block)
                # If far behind, use bulk mode via nectar.block.Blocks to catch up faster
                if backlog >= 300:
                    # Tuneable sizes
                    bulk_batch = min(1000, backlog + 1)
                    try:
                        current_app.logger.info(
                            "[watcher] bulk mode ON: backlog=%s start=%s batch=%s",
                            backlog,
                            next_block,
                            bulk_batch,
                        )
                    except Exception:
                        pass
                    # Blocks(start, limit, only_ops=True, ops=[...])
                    try:
                        blocks_iter = Blocks(
                            next_block,
                            bulk_batch,
                            only_ops=True,
                            ops=["custom_json_operation", "custom_json"],
                            blockchain_instance=hv,
                        )
                        processed_blocks = 0
                        total_inserted = 0
                        for blk in blocks_iter:
                            bn = getattr(blk, "block_num", None) or blk.get("block_num")
                            # Timestamp may be present on blk dict-like
                            ts = None
                            try:
                                ts = blk["timestamp"]
                            except Exception:
                                ts = getattr(blk, "timestamp", None)
                            dt = (
                                _parse_timestamp(ts)
                                if isinstance(ts, str)
                                else _utcnow_naive()
                            )

                            # Build tx-id mapping via helper (prefers get_ops_in_block, falls back to full block)
                            app_map, app_tx_ids = _ops_map_for_block(
                                hv, bn, current_app.config["APP_ID"]
                            )

                            # Iterate high-level operations
                            op_counter = 0
                            inserted_this_block = 0
                            # Track seen trx_ids within this block to avoid duplicates
                            seen_ids_block: set[str] = set()
                            for op in getattr(blk, "operations", []):
                                try:
                                    # Expect dict format {"type": ..., "value": {...}}
                                    optype = (
                                        op.get("type") if isinstance(op, dict) else None
                                    )
                                    payload = (
                                        op.get("value")
                                        if isinstance(op, dict)
                                        else None
                                    )
                                    if not payload:
                                        continue
                                    if optype not in (
                                        "custom_json_operation",
                                        "custom_json",
                                    ):
                                        continue
                                    if (
                                        payload.get("id")
                                        != current_app.config["APP_ID"]
                                    ):
                                        continue
                                    # Compute mapping key for preferred match (author, content)
                                    rpa = (
                                        payload.get("required_posting_auths", []) or []
                                    )
                                    ra = payload.get("required_auths", []) or []
                                    pauthor = rpa[0] if rpa else (ra[0] if ra else None)
                                    pcontent = None
                                    pbody = payload.get("json")
                                    if isinstance(pbody, str):
                                        try:
                                            pbody = json.loads(pbody)
                                        except Exception:
                                            pbody = None
                                    if (
                                        isinstance(pbody, dict)
                                        and pbody.get("type") == "post"
                                    ):
                                        pcontent = (pbody.get("content") or "").strip()
                                    trx_id_over = None
                                    if pauthor and pcontent:
                                        key = (str(pauthor), pcontent)
                                        q = app_map.get(key) or []
                                        if q:
                                            trx_id_over = q.pop(0)
                                    # Fallback: index-aligned order
                                    if trx_id_over is None and op_counter < len(
                                        app_tx_ids
                                    ):
                                        trx_id_over = app_tx_ids[op_counter]
                                    inserted = _ingest_custom_json_op(
                                        block_num=bn,
                                        dt=dt,
                                        payload=payload,
                                        tx_idx=0,
                                        op_idx=op_counter,
                                        trx_id_override=trx_id_over,
                                        seen_ids=seen_ids_block,
                                    )
                                    if inserted:
                                        # Commit periodically to keep transactions small
                                        if op_counter % 200 == 0:
                                            try:
                                                db.session.commit()
                                            except Exception:
                                                try:
                                                    db.session.rollback()
                                                except Exception:
                                                    pass
                                        inserted_this_block += inserted
                                    op_counter += 1
                                except Exception:
                                    continue
                            ck.last_block = bn
                            processed_blocks += 1
                            total_inserted += inserted_this_block
                            try:
                                current_app.logger.debug(
                                    "[watcher] bulk block=%s ops=%s",
                                    bn,
                                    inserted_this_block,
                                )
                            except Exception:
                                pass
                            # Commit at end of each block in bulk mode
                            try:
                                db.session.commit()
                            except Exception:
                                try:
                                    db.session.rollback()
                                except Exception:
                                    pass
                        try:
                            current_app.logger.info(
                                "[watcher] bulk mode processed blocks=%s inserted_ops=%s; last_block=%s",
                                processed_blocks,
                                total_inserted,
                                ck.last_block,
                            )
                        except Exception:
                            pass
                    except Exception:
                        # Fallback to single-block mode on errors
                        try:
                            current_app.logger.exception(
                                "[watcher] bulk mode error; falling back to single-block mode"
                            )
                        except Exception:
                            pass
                        batch_end = min(head, next_block + 50)
                        for bn in range(next_block, batch_end + 1):
                            _ingest_block(hv, bn)
                            ck.last_block = bn
                        db.session.commit()
                else:
                    # Process a small batch to avoid long transactions
                    try:
                        current_app.logger.debug(
                            "[watcher] single mode: next=%s to %s (head=%s)",
                            next_block,
                            min(head, next_block + 50),
                            head,
                        )
                    except Exception:
                        pass
                    batch_end = min(head, next_block + 50)
                    for bn in range(next_block, batch_end + 1):
                        _ingest_block(hv, bn)
                        ck.last_block = bn
                    db.session.commit()
                    # After processing in single mode, sleep close to block interval
                    try:
                        sleep_single = current_app.config.get(
                            "WATCHER_SINGLE_SLEEP_SEC", 2.5
                        )
                        current_app.logger.debug(
                            "[watcher] single mode batch done; sleeping %.2fs",
                            sleep_single,
                        )
                    except Exception:
                        sleep_single = 2.5
                    time.sleep(sleep_single)
            except Exception:
                # Backoff on errors
                try:
                    current_app.logger.exception("[watcher] error in loop; backing off")
                except Exception:
                    pass
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
