#!/usr/bin/env python3
"""
Inspect and compare operations returned via nectar.block.Blocks (only_ops) vs
full single-block RPC responses over a range of blocks.

Examples:
  # Inspect last 100 blocks (auto-detected head start)
  python scripts/inspect_ops.py

  # Start from a specific block and inspect 50
  python scripts/inspect_ops.py --start 99684000 --count 50

  # Limit to custom_json ops for a specific app id
  python scripts/inspect_ops.py --app-id hive.micro

Outputs human-readable summaries to stdout. Use --json for line-delimited JSON.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

# Allow running from repo root
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


def _plain(o: Any) -> str:
    try:
        return json.dumps(o, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(o)


def collect_blocks_only_ops(
    hv: Hive, start: int, count: int, app_id: Optional[str]
) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []
    it = Blocks(
        start,
        count,
        only_ops=True,
        ops=["custom_json_operation", "custom_json"],
        blockchain_instance=hv,
    )
    for blk in it:
        bn = (
            getattr(blk, "block_num", None)
            or getattr(blk, "block_num", None)
            or blk.get("block_num")
        )
        entry: Dict[str, Any] = {"block_num": bn, "ops": []}
        for op in getattr(blk, "operations", []) or []:
            if not isinstance(op, dict):
                continue
            t = op.get("type")
            v = op.get("value") if isinstance(op, dict) else None
            if app_id and (not isinstance(v, dict) or v.get("id") != app_id):
                continue
            entry["ops"].append(
                {
                    "type": t,
                    "id": (v or {}).get("id") if isinstance(v, dict) else None,
                    "has_transaction_id": isinstance(v, dict)
                    and ("transaction_id" in v),
                    "rpa_len": len((v or {}).get("required_posting_auths") or []),
                    "ra_len": len((v or {}).get("required_auths") or []),
                }
            )
        res.append(entry)
    return res


def collect_full_blocks(
    hv: Hive, start: int, count: int, app_id: Optional[str]
) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []
    for bn in range(start, start + count):
        blk = hv.rpc.get_block(bn) or {}
        txs = blk.get("transactions", []) or []
        entry: Dict[str, Any] = {"block_num": bn, "ops": []}
        for tx_idx, tx in enumerate(txs):
            trx = tx.get("transaction_id")
            ops = tx.get("operations", []) or []
            for op_idx, op in enumerate(ops):
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
                if app_id and (
                    not isinstance(payload, dict) or payload.get("id") != app_id
                ):
                    continue
                entry["ops"].append(
                    {
                        "type": t,
                        "id": (payload or {}).get("id")
                        if isinstance(payload, dict)
                        else None,
                        "transaction_id": trx,
                        "tx_idx": tx_idx,
                        "op_idx": op_idx,
                        "rpa_len": len(
                            (payload or {}).get("required_posting_auths") or []
                        ),
                        "ra_len": len((payload or {}).get("required_auths") or []),
                    }
                )
        res.append(entry)
    return res


def main():
    ap = argparse.ArgumentParser(
        description="Inspect custom_json ops via Blocks vs full block RPC"
    )
    ap.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start block number (default: head - count)",
    )
    ap.add_argument(
        "--count", type=int, default=100, help="Number of blocks to inspect"
    )
    ap.add_argument(
        "--app-id",
        type=str,
        default=None,
        help="Filter to a specific custom_json app id (e.g., hive.micro)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Output line-delimited JSON instead of human-readable summary",
    )

    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        hv = _get_hive(app)
        head = _get_head(hv)
        start = args.start if args.start is not None else max(1, head - args.count)
        # Collect
        blocks_only = collect_blocks_only_ops(hv, start, args.count, args.app_id)
        full_blocks = collect_full_blocks(hv, start, args.count, args.app_id)

        if args.json:
            print(
                json.dumps({"mode": "blocks_only", "start": start, "count": args.count})
            )
            for b in blocks_only:
                print(json.dumps(b, ensure_ascii=False))
            print(
                json.dumps({"mode": "full_blocks", "start": start, "count": args.count})
            )
            for b in full_blocks:
                print(json.dumps(b, ensure_ascii=False))
            return

        print(f"Inspecting blocks {start}..{start + args.count - 1}")
        print("=== Blocks iterator (only_ops) ===")
        for b in blocks_only:
            bn = b["block_num"]
            ops = b["ops"]
            print(f"block {bn}: ops={len(ops)}")
            for o in ops[:10]:  # show first 10 per block for brevity
                print(
                    f"  - type={o['type']} id={o.get('id')} has_txid={o.get('has_transaction_id')} "
                    f"rpa={o.get('rpa_len')} ra={o.get('ra_len')}"
                )
        print("\n=== Full single-block RPC ===")
        for b in full_blocks:
            bn = b["block_num"]
            ops = b["ops"]
            print(f"block {bn}: ops={len(ops)}")
            for o in ops[:10]:
                print(
                    f"  - type={o['type']} id={o.get('id')} txid={o.get('transaction_id')} tx_idx={o.get('tx_idx')} op_idx={o.get('op_idx')} "
                    f"rpa={o.get('rpa_len')} ra={o.get('ra_len')}"
                )


if __name__ == "__main__":
    main()
