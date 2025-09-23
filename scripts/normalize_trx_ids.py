#!/usr/bin/env python3
"""
Normalize synthetic trx_ids (e.g., "99684855-12-0") in the messages table to
real transaction hashes by reconciling with full block data from Hive.

Usage examples:
  python scripts/normalize_trx_ids.py --dry-run
  python scripts/normalize_trx_ids.py --start-block 99000000 --end-block 99700000
  python scripts/normalize_trx_ids.py --limit 500

Strategy:
- Select Message rows whose trx_id matches the synthetic pattern: ^\d+-\d+-\d+$
- Group by block_num.
- For each block, fetch the full block via nectar Hive RPC and enumerate all
  custom_json ops with id == APP_ID. Derive author and content from payload.
- Match DB rows to chain ops by (author, content). Update DB trx_id to the real
  transaction id if unique and not used by another row.
- Commit in small batches, log progress. Dry-run supported.

Notes:
- Requires app environment to be configured via env vars. Uses create_app().
- If a matching candidate cannot be found, the row is skipped.
- If a duplicate trx_id would be created, the row is skipped (unique constraint).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from nectar.hive import Hive

# Ensure imports resolve whether run from repo root or scripts/
if __name__ == "__main__":
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import create_app  # noqa: E402
from app.models import db, Message  # noqa: E402

SYNTH_TRX_RE = re.compile(r"^\d+-\d+-\d+$")


def _get_hive(app) -> Hive:
    try:
        return Hive(node=app.config.get("HIVE_NODES"))
    except Exception:
        return Hive()


def _extract_ops_for_app(
    full_block: Dict[str, Any], app_id: str
) -> List[Dict[str, Any]]:
    """Return list of ops with fields: {trx_id, author, content} for our app."""
    results: List[Dict[str, Any]] = []
    txs = full_block.get("transactions", []) or []
    for tx in txs:
        trx_id = tx.get("transaction_id")
        for op in tx.get("operations", []) or []:
            try:
                if not isinstance(op, (list, tuple)) or len(op) != 2:
                    continue
                op_type, payload = op
                if op_type != "custom_json":
                    continue
                # Normalize payload
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                if not isinstance(payload, dict):
                    continue
                if payload.get("id") != app_id:
                    continue
                # Author
                rpa = payload.get("required_posting_auths", []) or []
                ra = payload.get("required_auths", []) or []
                author = rpa[0] if rpa else (ra[0] if ra else None)
                if not author:
                    continue
                # Body
                body = payload.get("json")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        body = None
                if not isinstance(body, dict):
                    continue
                if body.get("type") != "post":
                    continue
                content = (body.get("content") or "").strip()
                if not content:
                    continue
                results.append(
                    {
                        "trx_id": trx_id,
                        "author": author,
                        "content": content,
                    }
                )
            except Exception:
                continue
    return results


def normalize_trx_ids(
    start_block: Optional[int],
    end_block: Optional[int],
    limit: Optional[int],
    batch_size: int,
    dry_run: bool,
) -> Tuple[int, int, int]:
    app = create_app()
    updated = 0
    examined = 0
    skipped = 0

    with app.app_context():
        hv = _get_hive(app)
        app_id = app.config.get("APP_ID", "hive.micro")
        # Portable selection: SQLite lacks REGEXP by default. Filter by '-' and then validate via regex in Python.
        q = Message.query.filter(Message.trx_id.contains("-"))
        if start_block is not None:
            q = q.filter(Message.block_num >= start_block)
        if end_block is not None:
            q = q.filter(Message.block_num <= end_block)
        # Order by block_num ascending for stable processing
        q = q.order_by(Message.block_num.asc(), Message.id.asc())
        if limit is not None and limit > 0:
            q = q.limit(limit)

        # Fetch rows and group by block
        # Pull rows and filter synthetic ids via regex client-side
        rows: List[Message] = [r for r in list(q) if SYNTH_TRX_RE.match(r.trx_id or "")]
        if not rows:
            app.logger.info("[normalize] no synthetic trx_ids found in selected range.")
            return updated, examined, skipped

        # Group rows by block_num
        by_block: Dict[int, List[Message]] = {}
        for r in rows:
            by_block.setdefault(r.block_num, []).append(r)

        for block_num, msgs in by_block.items():
            examined += len(msgs)
            try:
                full_blk = hv.rpc.get_block(block_num) or {}
                ops = _extract_ops_for_app(full_blk, app_id)
                if not ops:
                    app.logger.debug(
                        "[normalize] block=%s has no matching ops; skipping %s msgs",
                        block_num,
                        len(msgs),
                    )
                    skipped += len(msgs)
                    continue
                # Build candidates by (author, content) -> list of trx_ids (in order)
                from collections import defaultdict

                cand: Dict[Tuple[str, str], List[str]] = defaultdict(list)
                for o in ops:
                    if not o.get("trx_id"):
                        # Fallback shouldn't generally happen, but keep safe
                        continue
                    k = (o["author"], o["content"])
                    cand[k].append(o["trx_id"])

                # Iterate messages and update when an exact match exists
                for m in msgs:
                    key = (m.author, (m.content or "").strip())
                    tx_list = cand.get(key) or []
                    if not tx_list:
                        skipped += 1
                        continue
                    # If multiple candidates, pop one deterministically (FIFO)
                    real_trx = tx_list.pop(0)
                    # Uniqueness guard: skip if another row already has this trx_id
                    existing = Message.query.filter(Message.trx_id == real_trx).first()
                    if existing and existing.id != m.id:
                        skipped += 1
                        continue
                    if m.trx_id == real_trx:
                        skipped += 1
                        continue
                    app.logger.info(
                        "[normalize] block=%s id=%s: %s -> %s",
                        block_num,
                        m.id,
                        m.trx_id,
                        real_trx,
                    )
                    if not dry_run:
                        m.trx_id = real_trx
                        db.session.add(m)
                        updated += 1
                        if updated % batch_size == 0:
                            db.session.commit()
                if not dry_run:
                    db.session.commit()
            except Exception:
                app.logger.exception(
                    "[normalize] error while processing block=%s", block_num
                )
                db.session.rollback()
                continue

    return updated, examined, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Normalize synthetic trx_ids to real transaction hashes"
    )
    parser.add_argument(
        "--start-block", type=int, default=None, help="Start block number (inclusive)"
    )
    parser.add_argument(
        "--end-block", type=int, default=None, help="End block number (inclusive)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max number of rows to process"
    )
    parser.add_argument(
        "--batch-size", type=int, default=200, help="Commit after this many updates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write changes; just log what would be updated",
    )

    args = parser.parse_args()
    updated, examined, skipped = normalize_trx_ids(
        start_block=args.start_block,
        end_block=args.end_block,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    print(
        f"Normalization complete: updated={updated} examined={examined} skipped={skipped} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
