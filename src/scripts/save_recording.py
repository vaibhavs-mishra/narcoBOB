"""Save the latest live session as the replay recording (`make replay` serves it).

Copies the newest `recordings/session_*.jsonl` to `recordings/demo_golden.jsonl` and
snapshots the live database (SQLite online backup, safe while the API runs) to
`recordings/demo_golden.db`, which answers the replay's REST lookups.

    uv run python scripts/save_recording.py            # uses NARCOBOB_DB_PATH
    uv run python scripts/save_recording.py --db var/other.db --name demo_golden
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

from narcobob.common.config import SRC_DIR, get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=None, help="live database (default: config)")
    parser.add_argument("--name", default="demo_golden")
    args = parser.parse_args()

    recordings = SRC_DIR / "recordings"
    sessions = sorted(recordings.glob("session_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise SystemExit("no session recording yet: run the live API with NARCOBOB_RECORD=true")
    target = recordings / f"{args.name}.jsonl"
    shutil.copyfile(sessions[-1], target)

    db = args.db if args.db is not None else get_settings().db_file
    db = db if db.is_absolute() else SRC_DIR / db
    snapshot = recordings / f"{args.name}.db"
    snapshot.unlink(missing_ok=True)
    with sqlite3.connect(db) as src, sqlite3.connect(snapshot) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")  # a single self-contained file
    lines = sum(1 for _ in target.open())
    print(f"{target.name}: {lines} messages from {sessions[-1].name}")
    print(f"{snapshot.name}: {snapshot.stat().st_size / 1e6:.1f} MB from {db.name}")


if __name__ == "__main__":
    main()
