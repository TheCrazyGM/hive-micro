#!/usr/bin/env python3
"""
Normalize synthetic trx_ids (e.g., "99684855-12-0") in the messages table to
real transaction hashes by reconciling with chain data.

Usage examples:
  python scripts/normalize_trx_ids.py --dry-run
  python scripts/normalize_trx_ids.py --start-block 99000000 --end-block 99700000
  python scripts/normalize_trx_ids.py --limit 500 --batch-size 200

Strategy:
- Select Message rows whose trx_id looks synthetic: r"^\\d+-\\d+-\\d+$" (client-side regex).
- Group by block_num.
- For each block, pull ops via hv.rpc.get_ops_in_block(bn, True) and build a map
  of (author, content) -> [transaction_id].
- For each message in that block, match by (author, content) and update trx_id
  when a unique candidate exists and does not violate the unique constraint.
- Commit in small batches; support --dry-run.

Requires app environment (DB, nodes) via create_app().
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Allow running from repo root
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from nectar.hive import Hive
from dotenv import load_dotenv

from app import create_app
from app.models import db, Message

SYNTH_TRX_RE = re.compile(r"^\d+-\d+-\d+$")

# Load environment variables from a .env file if present (e.g., DATABASE_URL, APP_ID)
load_dotenv()


def _get_hive(app) -> Hive:
    try:
        return Hive(node=app.config.get("HIVE_NODES"))
    except Exception:
        return Hive()


def _trx_from(opd: Dict[str, Any]) -> Optional[str]:
    for k in ("transaction_id", "trx_id", "trxId"):
        v = opd.get(k)
        if v:
            return str(v)
    return None


def _ops_map_for_block(
    hv: Hive, bn: int, app_id: str
) -> Tuple[Dict[Tuple[str, str], List[str]], List[str]]:
    """Return (map, order) for our app's custom_json ops in a block.
    - map: (author, content) -> [trx_ids]
    - order: [trx_ids] in the order ops were seen in the block (for index fallback)
    """
    mp: Dict[Tuple[str, str], List[str]] = {}
    order: List[str] = []
    raw_ops = hv.rpc.get_ops_in_block(bn, True) or []
    for ro in raw_ops:
        try:
            op_pair = ro.get("op") if isinstance(ro, dict) else None
            if not isinstance(op_pair, (list, tuple)) or len(op_pair) != 2:
                continue
            t, pl = op_pair
            if t != "custom_json":
                continue
            # normalize payload
            if isinstance(pl, str):
                try:
                    pl = json.loads(pl)
                except Exception:
                    pl = {}
            if not isinstance(pl, dict):
                continue
            if pl.get("id") != app_id:
                continue
            # author
            rpa = pl.get("required_posting_auths", []) or []
            ra = pl.get("required_auths", []) or []
            author = rpa[0] if rpa else (ra[0] if ra else None)
            if not author:
                continue
            # content
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
            txh = _trx_from(ro)
            if not txh:
                continue
            key = (str(author), content)
            mp.setdefault(key, []).append(txh)
            order.append(txh)
        except Exception:
            continue
    return mp, order


def normalize_trx_ids(
    start_block: Optional[int],
    end_block: Optional[int],
    limit: Optional[int],
    batch_size: int,
    dry_run: bool,
    one_trx: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int, int]:
    app = create_app()
    updated = 0
    examined = 0
    skipped = 0

    with app.app_context():
        hv = _get_hive(app)
        app_id = app.config.get("APP_ID", "hive.micro")
        # broad query then client-side filter to be portable across SQLite/Postgres
        q = Message.query
        if one_trx:
            q = q.filter(Message.trx_id == one_trx)
        else:
            q = q.filter(Message.trx_id.contains("-"))
        if start_block is not None:
            q = q.filter(Message.block_num >= start_block)
        if end_block is not None:
            q = q.filter(Message.block_num <= end_block)
        q = q.order_by(Message.block_num.asc(), Message.id.asc())
        if limit is not None and limit > 0:
            q = q.limit(limit)
        rows_all: List[Message] = list(q)
        rows: List[Message] = (
            rows_all
            if one_trx
            else [r for r in rows_all if SYNTH_TRX_RE.match(r.trx_id or "")]
        )
        if verbose:
            try:
                uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
                # mask password
                if "://" in uri and "@" in uri:
                    scheme, rest = uri.split("://", 1)
                    creds, host = rest.split("@", 1)
                    if ":" in creds:
                        user, _pw = creds.split(":", 1)
                        uri = f"{scheme}://{user}:***@{host}"
                app.logger.info(
                    "[normalize] DB=%s app_id=%s prefilter_rows=%s synthetic_rows=%s",
                    uri,
                    app_id,
                    len(rows_all),
                    len(rows),
                )
            except Exception:
                pass
        if not rows:
            app.logger.info("[normalize] no synthetic trx_ids found in selected range.")
            return updated, examined, skipped

        # group by block
        by_block: Dict[int, List[Message]] = {}
        for r in rows:
            by_block.setdefault(r.block_num, []).append(r)

        for bn, msgs in by_block.items():
            examined += len(msgs)
            try:
                mp, order_tx = _ops_map_for_block(hv, bn, app_id)
                if not mp and not order_tx:
                    skipped += len(msgs)
                    continue
                used: set[str] = set()
                for m in msgs:
                    key = (m.author, (m.content or "").strip())
                    # primary: content-based
                    real_trx: Optional[str] = None
                    cand = mp.get(key) or []
                    while cand and (cand[0] in used):
                        cand.pop(0)
                    if cand:
                        real_trx = cand.pop(0)
                    # fallback: index-aligned order across app ops in this block
                    if real_trx is None and INDEX_FALLBACK:
                        while order_tx and (order_tx[0] in used):
                            order_tx.pop(0)
                        if order_tx:
                            real_trx = order_tx.pop(0)
                            if verbose:
                                try:
                                    app.logger.info(
                                        "[normalize] fallback(index) block=%s id=%s assigned_tx=%s",
                                        bn,
                                        m.id,
                                        real_trx,
                                    )
                                except Exception:
                                    pass
                    if not real_trx:
                        if verbose:
                            try:
                                app.logger.info(
                                    "[normalize] skip(no-match) block=%s id=%s key=%s",
                                    bn,
                                    m.id,
                                    key,
                                )
                            except Exception:
                                pass
                        skipped += 1
                        continue
                    # uniqueness guard
                    existing = Message.query.filter(Message.trx_id == real_trx).first()
                    if existing and existing.id != m.id:
                        if verbose:
                            try:
                                app.logger.info(
                                    "[normalize] skip(dup) block=%s id=%s candidate=%s existing_id=%s",
                                    bn,
                                    m.id,
                                    real_trx,
                                    existing.id,
                                )
                            except Exception:
                                pass
                        skipped += 1
                        continue
                    if m.trx_id == real_trx:
                        used.add(real_trx)
                        skipped += 1
                        continue
                    app.logger.info(
                        "[normalize] block=%s id=%s: %s -> %s",
                        bn,
                        m.id,
                        m.trx_id,
                        real_trx,
                    )
                    if not dry_run:
                        m.trx_id = real_trx
                        db.session.add(m)
                        updated += 1
                        used.add(real_trx)
                        if updated % batch_size == 0:
                            db.session.commit()
                if not dry_run:
                    db.session.commit()
            except Exception:
                app.logger.exception("[normalize] error while processing block=%s", bn)
                db.session.rollback()
                continue

    return updated, examined, skipped


def main():
    ap = argparse.ArgumentParser(
        description="Normalize synthetic trx_ids to real transaction hashes"
    )
    ap.add_argument(
        "--start-block", type=int, default=None, help="Start block number (inclusive)"
    )
    ap.add_argument(
        "--end-block", type=int, default=None, help="End block number (inclusive)"
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="Max number of rows to process"
    )
    ap.add_argument(
        "--batch-size", type=int, default=200, help="Commit after this many updates"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write changes; just log what would be updated",
    )
    ap.add_argument(
        "--one-trx-id",
        type=str,
        default=None,
        help="Normalize a single specific trx_id (useful for spot fixes like 99684855-12-0)",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostics (DB URI masked, prefilter counts)",
    )
    ap.add_argument(
        "--index-fallback",
        action="store_true",
        help="When content match fails, fall back to assigning by app-op order in the block",
    )

    args = ap.parse_args()
    # Expose index-fallback via a module-level flag to keep function signature simple for internal calls
    global INDEX_FALLBACK
    INDEX_FALLBACK = args.index_fallback

    updated, examined, skipped = normalize_trx_ids(
        start_block=args.start_block,
        end_block=args.end_block,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        one_trx=args.one_trx_id,
        verbose=args.verbose,
    )
    print(
        f"Normalization complete: updated={updated} examined={examined} skipped={skipped} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
