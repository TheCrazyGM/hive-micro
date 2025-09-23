#!/usr/bin/env python3
"""
Compare per-block data returned by nectar.block.Blocks (bulk/only_ops) with the
full single-block RPC for the same block numbers.

Purpose: verify that Blocks iterator and full RPC match in structure and counts.

Usage examples:
  # Compare last 20 blocks
  python scripts/compare_bulk_block.py

  # Compare specific range
  python scripts/compare_bulk_block.py --start 99685600 --count 10

  # Filter to a custom_json app id (reduces noise)
  python scripts/compare_bulk_block.py --app-id hive.micro

  # JSON lines output for machine diffing
  python scripts/compare_bulk_block.py --json
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from nectar.block import Blocks
from nectar.hive import Hive

from app import create_app


def _get_hive(app) -> Hive:
    try:
        return Hive(node=app.config.get("HIVE_NODES"))
    except Exception:
        return Hive()


def _get_head(hv: Hive) -> int:
    props = hv.rpc.get_dynamic_global_properties() or {}
    return props.get("head_block_number") or props.get("last_irreversible_block_num")


def main():
    ap = argparse.ArgumentParser(
        description="Compare Blocks iterator output with full RPC blocks"
    )
    ap.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start block number (default: head - count)",
    )
    ap.add_argument("--count", type=int, default=20, help="Number of blocks to compare")
    ap.add_argument(
        "--app-id",
        type=str,
        default=None,
        help="Filter to custom_json app id (e.g. hive.micro)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Output JSON lines for each block with both views",
    )

    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        hv = _get_hive(app)
        head = _get_head(hv)
        start = args.start if args.start is not None else max(1, head - args.count)

        # Collect bulk (Blocks) view
        blocks_view: Dict[int, Dict[str, Any]] = {}
        it = Blocks(
            start,
            args.count,
            only_ops=True,
            ops=["custom_json_operation", "custom_json"],
            blockchain_instance=hv,
        )
        for blk in it:
            bn = getattr(blk, "block_num", None) or blk.get("block_num")
            ops_list = []
            for op in getattr(blk, "operations", []) or []:
                if not isinstance(op, dict):
                    continue
                t = op.get("type")
                v = op.get("value") if isinstance(op, dict) else None
                if args.app_id and (
                    not isinstance(v, dict) or v.get("id") != args.app_id
                ):
                    continue
                ops_list.append(
                    {
                        "type": t,
                        "id": (v or {}).get("id") if isinstance(v, dict) else None,
                        # note: Blocks ops typically don't carry transaction_id
                        "has_txid": bool(
                            isinstance(v, dict) and ("transaction_id" in v)
                        ),
                    }
                )
            blocks_view[int(bn)] = {
                "block_num": int(bn),
                "ops": ops_list,
                "op_count": len(ops_list),
            }

        # Collect full RPC view for same blocks
        full_view: Dict[int, Dict[str, Any]] = {}
        for bn in range(start, start + args.count):
            blk = hv.rpc.get_block(bn) or {}
            txs = blk.get("transactions", []) or []
            ops_list = []
            for tx in txs:
                trx_id = tx.get("transaction_id")
                for op in tx.get("operations", []) or []:
                    if not isinstance(op, (list, tuple)) or len(op) != 2:
                        continue
                    t, payload = op
                    if t != "custom_json":
                        continue
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    if args.app_id and (
                        not isinstance(payload, dict)
                        or payload.get("id") != args.app_id
                    ):
                        continue
                    ops_list.append(
                        {
                            "type": t,
                            "id": (payload or {}).get("id")
                            if isinstance(payload, dict)
                            else None,
                            "transaction_id": trx_id,
                        }
                    )
            full_view[int(bn)] = {
                "block_num": int(bn),
                "ops": ops_list,
                "op_count": len(ops_list),
            }

        # Output
        if args.json:
            for bn in range(start, start + args.count):
                print(
                    json.dumps(
                        {
                            "block": bn,
                            "blocks_iter": blocks_view.get(bn, {}),
                            "full_rpc": full_view.get(bn, {}),
                            "counts": {
                                "blocks_iter": blocks_view.get(bn, {}).get(
                                    "op_count", 0
                                ),
                                "full_rpc": full_view.get(bn, {}).get("op_count", 0),
                            },
                        },
                        ensure_ascii=False,
                    )
                )
            return

        print(f"Comparing blocks {start}..{start + args.count - 1}")
        for bn in range(start, start + args.count):
            b = blocks_view.get(bn, {"op_count": 0})
            f = full_view.get(bn, {"op_count": 0})
            print(
                f"block {bn}: blocks_iter_ops={b.get('op_count')} full_rpc_ops={f.get('op_count')}"
            )
            # Show a few sample ops from each
            bi = (b.get("ops") or [])[:5]
            fr = (f.get("ops") or [])[:5]
            if bi:
                print("  blocks_iter ops (first 5):")
                for o in bi:
                    print(
                        f"    - type={o.get('type')} id={o.get('id')} has_txid={o.get('has_txid')}"
                    )
            if fr:
                print("  full_rpc ops (first 5):")
                for o in fr:
                    print(
                        f"    - type={o.get('type')} id={o.get('id')} txid={o.get('transaction_id')}"
                    )


if __name__ == "__main__":
    main()
