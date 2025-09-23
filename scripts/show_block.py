#!/usr/bin/env python3
"""
Show the full raw block JSON from the Hive RPC for a specific block number.

Usage:
  # Show a specific block (pretty-printed JSON)
  python scripts/show_block.py --block 99685600

  # Output as compact JSON (single line)
  python scripts/show_block.py --block 99685600 --compact

If you prefer to pick a block via the bulk iterator, you can pass --from-bulk-start
and --from-bulk-count to first enumerate via nectar.block.Blocks and select the
first block number it returns, then fetch the full block via RPC.

Examples:
  # Take the first block from a 100-count bulk window and show its full JSON
  python scripts/show_block.py --from-bulk-start 99685600 --from-bulk-count 100
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

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


def main():
    ap = argparse.ArgumentParser(description="Show full block JSON from Hive RPC")
    ap.add_argument("--block", type=int, default=None, help="Block number to fetch")
    ap.add_argument(
        "--compact", action="store_true", help="Print compact JSON (one line)"
    )
    ap.add_argument(
        "--from-bulk-start",
        type=int,
        default=None,
        help="Start block for Blocks iterator (use first returned block)",
    )
    ap.add_argument(
        "--from-bulk-count",
        type=int,
        default=100,
        help="Count for Blocks iterator (used with --from-bulk-start)",
    )

    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        hv = _get_hive(app)

        block_num: Optional[int] = args.block
        if block_num is None and args.from_bulk_start is not None:
            # Enumerate via Blocks and take the first block number it yields
            it = Blocks(
                args.from_bulk_start,
                args.from_bulk_count,
                only_ops=True,
                ops=["custom_json_operation", "custom_json"],
                blockchain_instance=hv,
            )
            try:
                blk = next(iter(it))
                block_num = getattr(blk, "block_num", None) or blk.get("block_num")
            except StopIteration:
                print(
                    "No blocks returned by bulk iterator in the given range",
                    file=sys.stderr,
                )
                sys.exit(1)
        if block_num is None:
            print("You must provide --block or --from-bulk-start", file=sys.stderr)
            sys.exit(1)

        full_block: Dict[str, Any] = hv.rpc.get_block(block_num) or {}
        if args.compact:
            print(json.dumps(full_block, ensure_ascii=False))
        else:
            print(json.dumps(full_block, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
