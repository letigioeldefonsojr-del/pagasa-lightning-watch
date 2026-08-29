#!/usr/bin/env python3
"""One-shot poll: fetch whatever PAGASA lightning strikes are currently
being reported, merge them into docs/data/pagasa_lightning_log.csv
(the full history) and docs/data/pagasa_lightning_latest.json (a trimmed
feed for the dashboard), then exit.

This is NOT a long-running watch loop like watch_lightning() in
radar_to_tiff.py -- it's meant to be invoked fresh by the GitHub Actions
workflow on a schedule (every ~15 min), since a single Action job can't
stay alive indefinitely (GitHub kills jobs at 6 hours regardless, and
schedule reliability is best-effort anyway). Because each run is a brand
new process with no memory of previous runs, dedup state is rebuilt by
re-reading the CSV that's already committed in the repo -- the CSV itself
IS the durable "seen" set across runs, not an in-memory dict like the
watch functions use.
"""
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import radar_to_tiff as core  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "data"
CSV_PATH = OUT_DIR / "pagasa_lightning_log.csv"
JSON_PATH = OUT_DIR / "pagasa_lightning_latest.json"
FIELDS = core.LIGHTNING_LOG_FIELDS
MAX_JSON_ROWS = 500  # the dashboard only needs recent strikes, not the full history


def dedup_key(row: dict):
    return (row.get("timestamp"), row.get("latitude"), row.get("longitude"))


def load_existing() -> list:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_csv(rows: list):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def save_json(rows: list, new_count: int):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "total_strikes": len(rows),
        "new_this_run": new_count,
        "strikes": rows[-MAX_JSON_ROWS:],
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main():
    existing = load_existing()
    seen = {dedup_key(row) for row in existing}

    try:
        strikes = core.fetch_lightning()
    except Exception as e:
        # Don't fail the whole workflow run over a transient PAGASA hiccup
        # (a timeout, a 5xx, etc.) -- just log it and leave the existing
        # data untouched; the next scheduled run tries again in ~15 min.
        print(f"[poll error, will retry next run] {e}")
        strikes = []

    new_rows = []
    for s in strikes:
        key = dedup_key(s)
        if key not in seen:
            seen.add(key)
            new_rows.append(s)

    all_rows = existing + new_rows
    save_csv(all_rows)
    save_json(all_rows, len(new_rows))

    print(f"+{len(new_rows)} new strike(s) -- {len(all_rows)} total in {CSV_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
