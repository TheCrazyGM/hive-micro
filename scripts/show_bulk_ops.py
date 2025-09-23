#!/usr/bin/env python3
"""
Show the raw JSON-like structures from the bulk iterator (nectar.block.Blocks with only_ops=True)
so you can inspect exactly what the flattened bulk returns.

Usage examples:
  # Show first 5 blocks from a start point
  python scripts/show_bulk_ops.py --start 99685600 --count 5

  # Also show raw get_ops_in_block for comparison
  python scripts/show_bulk_ops.py --start 99685600 --count 1 --include-ops-in-block
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Allow running from repo root
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from nectar.block import Blocks
from nectar.hive import Hive

from app import create_app


def _get_hive(app) -> Hive:
    try:
        return Hive(node=app.config.get("HIVE_NODES"))
    except Exception:
        return Hive()


def to_jsonable(obj: Any) -> Any:
    """Best-effort conversion to something json.dumps can handle."""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    # Try dict-like access
    try:
        return {
            k: to_jsonable(getattr(obj, k)) for k in dir(obj) if not k.startswith("_")
        }
    except Exception:
        try:
            return str(obj)
        except Exception:
            return None


def main():
    ap = argparse.ArgumentParser(
        description="Show raw flattened bulk ops from nectar.block.Blocks"
    )
    ap.add_argument(
        "--start",
        type=int,
        required=True,
        help="Start block number for Blocks iterator",
    )
    ap.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of blocks to fetch via Blocks iterator",
    )
    ap.add_argument(
        "--include-ops-in-block",
        action="store_true",
        help="Also print raw get_ops_in_block for each block",
    )

    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        hv = _get_hive(app)

        it = Blocks(
            args.start,
            args.count,
            only_ops=True,
            ops=["custom_json_operation", "custom_json"],
            blockchain_instance=hv,
        )

        for blk in it:
            bn = getattr(blk, "block_num", None) or (
                blk.get("block_num") if isinstance(blk, dict) else None
            )
            ts = getattr(blk, "timestamp", None)
            if ts is None and isinstance(blk, dict):
                ts = blk.get("timestamp")
            print("==== BULK BLOCK ====")
            print(f"block_num: {bn}")
            print(f"timestamp: {ts}")
            # Print raw operations exactly as provided by the iterator
            print("operations (raw):")
            for i, op in enumerate(getattr(blk, "operations", []) or []):
                try:
                    print(json.dumps(op, ensure_ascii=False, indent=2))
                except TypeError:
                    print(json.dumps(to_jsonable(op), ensure_ascii=False, indent=2))
            if args.include_ops_in_block and bn is not None:
                print("==== get_ops_in_block (raw) ====")
                try:
                    raw_ops = hv.rpc.get_ops_in_block(int(bn), True) or []
                    print(json.dumps(raw_ops, ensure_ascii=False, indent=2))
                except Exception as e:
                    print(f"get_ops_in_block error: {e}")


if __name__ == "__main__":
    main()
