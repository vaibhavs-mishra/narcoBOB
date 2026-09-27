"""Save the latest live session as the replay recording (`make replay` serves it).

Copies the newest `recordings/session_*.jsonl` to `recordings/demo_golden.jsonl.gz` and
snapshots the live database (SQLite online backup, safe while the API runs) to
`recordings/demo_golden.db.gz`, which answers the replay's REST lookups. Both are gzipped
(the JSONL shrinks about 10×) so they can live in git.

    uv run python scripts/save_recording.py            # uses NARCOBOB_DB_PATH
    uv run python scripts/save_recording.py --db var/other.db --name demo_golden
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
from pathlib import Path

from narcobob.common.config import SRC_DIR, get_settings


def trim_after_report(frames: list[str], n: int, tail_s: float = 20.0) -> list[str]:
    """Keep frames up to `tail_s` seconds after the n-th `report.ready` message."""
    seen, cut_at = 0, None
    for line in frames:
        frame = json.loads(line)
        if cut_at is None and frame["msg"]["type"] == "report.ready":
            seen += 1
            if seen == n:
                cut_at = frame["t"] + tail_s
    if cut_at is None:
        raise SystemExit(f"the session has only {seen} brief(s); cannot trim after #{n}")
    return [line for line in frames if json.loads(line)["t"] <= cut_at]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=None, help="live database (default: config)")
    parser.add_argument("--name", default="demo_golden")
    parser.add_argument(
        "--trim-after-report",
        type=int,
        default=0,
        metavar="N",
        help="end the recording 20 s after the N-th brief is published (0 = keep all)",
    )
    args = parser.parse_args()

    recordings = SRC_DIR / "recordings"
    sessions = sorted(recordings.glob("session_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise SystemExit("no session recording yet: run the live API with NARCOBOB_RECORD=true")
    target = recordings / f"{args.name}.jsonl.gz"
    frames = sessions[-1].read_text(encoding="utf-8").splitlines()
    if args.trim_after_report:
        frames = trim_after_report(frames, args.trim_after_report)
    with gzip.open(target, "wt", encoding="utf-8") as out:
        out.write("\n".join(frames) + "\n")

    db = args.db if args.db is not None else get_settings().db_file
    db = db if db.is_absolute() else SRC_DIR / db
    plain = recordings / f"{args.name}.db"
    plain.unlink(missing_ok=True)
    with sqlite3.connect(db) as src, sqlite3.connect(plain) as dst:
        src.backup(dst)
    with sqlite3.connect(plain) as dst:
        dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file
        dst.execute("VACUUM")
    snapshot = recordings / f"{args.name}.db.gz"
    with plain.open("rb") as src_file, gzip.open(snapshot, "wb") as out:
        shutil.copyfileobj(src_file, out)
    plain.unlink()
    with gzip.open(target, "rt") as fh:
        lines = sum(1 for _ in fh)
    print(
        f"{target.name}: {lines} messages from {sessions[-1].name},"
        f" {target.stat().st_size / 1e6:.1f} MB"
    )
    print(f"{snapshot.name}: {snapshot.stat().st_size / 1e6:.1f} MB from {db.name}")


if __name__ == "__main__":
    main()
