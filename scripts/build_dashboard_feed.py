#!/usr/bin/env python3
"""Regenerates docs/data/pagasa_lightning_latest.json (the dashboard's
data feed) from whatever CSV log file(s) currently exist under
docs/data/.

This is its own step, separate from the watch itself, because
watch_and_commit.py's continuous watch (via core.watch_lightning() /
core.watch_lightning_panahon()) writes ONE CSV per job run -- each run
gets a fresh, timestamped filename (that's how those functions have
always worked, same as running them locally). Over many scheduled runs
that means several/many CSV files accumulate in docs/data/, each covering
its own stretch of time -- this script merges all of them (deduped, same
key as the watch functions use) into the single trimmed JSON feed the
dashboard actually reads, so the website doesn't need to know how many
segment files exist or what they're named.
"""
import csv
import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
JSON_PATH = DATA_DIR / "pagasa_lightning_latest.json"
MAX_JSON_ROWS = 500

# Matches filenames from both watch_lightning() (pagasa) and
# watch_lightning_panahon() -- e.g. pagasa_lightning_log_*.csv,
# panahon_lightning_log_*.csv, and their --window/--split variants, should
# this ever be pointed at those modes instead of plain continuous.
CSV_GLOBS = ["pagasa_lightning_*.csv", "panahon_lightning_*.csv"]


def dedup_key(row: dict):
    return (row.get("timestamp"), row.get("latitude"), row.get("longitude"))


def main():
    if not DATA_DIR.exists():
        return

    csv_paths = []
    for pattern in CSV_GLOBS:
        csv_paths.extend(DATA_DIR.glob(pattern))
    csv_paths = sorted(set(csv_paths))

    seen = {}
    for path in csv_paths:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    seen[dedup_key(row)] = row  # last write wins on an exact duplicate
        except (OSError, csv.Error) as e:
            print(f"  [skipping unreadable {path.name}: {e}]")

    all_rows = list(seen.values())
    # Rows don't carry a reliable shared sort field across both pagasa and
    # panahon schemas beyond "timestamp" (format varies by source) -- file
    # order + dict insertion order already reflects chronological order
    # well enough for "most recent N for the dashboard", so no re-sort here.

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "total_strikes": len(all_rows),
        "segment_count": len(csv_paths),
        "latest_strike_timestamp": all_rows[-1]["timestamp"] if all_rows else None,
        "strikes": all_rows[-MAX_JSON_ROWS:],
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  dashboard feed: {len(all_rows)} total strike(s) across {len(csv_paths)} file(s)")


if __name__ == "__main__":
    main()
