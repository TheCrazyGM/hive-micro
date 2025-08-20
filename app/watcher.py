"""
Standalone block-watcher sidecar process.

Runs only the background ingestion loop using the same app context
and configuration as the web app. Intended to be deployed as a
separate process/container so web workers can set HIVE_MICRO_WATCHER=0.

Usage examples:
  python -m app.watcher
  HIVE_MICRO_WATCHER=1 python -m app.watcher

Environment:
  - HIVE_MICRO_WATCHER: defaults to 1 in this sidecar. Set to 0 to disable.
  - All other app env vars (DB, Hive nodes, etc.) are honored via create_app().
"""

import os
import signal
import sys
import time

from . import create_app
from .helpers import stop_block_watcher


def main():
    # Ensure watcher is enabled for the sidecar
    os.environ.setdefault("HIVE_MICRO_WATCHER", "1")

    create_app()

    # create_app() already starts the watcher (gated by HIVE_MICRO_WATCHER)
    print("[watcher] sidecar started; watcher thread should be running.", flush=True)

    # Handle termination signals for graceful shutdown
    def _handle_sig(signum, frame):
        print(f"[watcher] received signal {signum}; stopping watcher...", flush=True)
        try:
            stop_block_watcher()
        finally:
            # Give a brief moment for clean exit
            time.sleep(0.2)
            sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    # Keep the process alive while the thread does the work
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        _handle_sig(signal.SIGINT, None)


if __name__ == "__main__":
    main()
