#!/usr/bin/env python3
"""Runs radar_to_tiff.py's REAL continuous watch (watch_lightning() for
pagasa, or watch_lightning_panahon() for panahon's live push feed) inside
a single GitHub Actions job, committing + pushing whatever's new every few
minutes, and stopping itself gracefully well before GitHub's hard 6-hour
job limit -- so the CSV it's writing gets a clean final commit instead of
being cut off mid-write, and the *next* scheduled job (which starts before
this one's self-imposed stop time) picks up watching with little to no
gap in between.

This is deliberately NOT a "poll once and exit" script -- that was the
first version, and it only checked in every 15 minutes, which meant real
gaps whenever PAGASA's own rolling window is shorter than that. This
script uses the actual continuous watch functions (60s polling for
pagasa; an always-open connection for panahon), which is what makes this
close to gapless.

Environment variables (all optional, sensible defaults below):
    LIGHTNING_SOURCE       "panahon" (default) or "pagasa"
    MAX_RUNTIME_SECONDS    self-imposed stop time (default 21000 = 5h50m,
                            comfortably under GitHub's 6h hard kill)
    COMMIT_INTERVAL_SECONDS  how often to commit+push while watching
                            (default 300 = 5 min)
"""
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import radar_to_tiff as core  # noqa: E402
import build_dashboard_feed  # noqa: E402

OUTDIR = REPO_ROOT / "docs" / "data"
SOURCE = os.environ.get("LIGHTNING_SOURCE", "panahon").strip().lower()
MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_SECONDS", "21000"))  # 5h50m
COMMIT_INTERVAL_SECONDS = int(os.environ.get("COMMIT_INTERVAL_SECONDS", "300"))  # 5 min
# Rotate into a new CSV every N minutes instead of one file per job run
# (matches the desktop tool's --split behavior). Set SPLIT_MINUTES=0 to
# turn this off and go back to one continuous file per job run.
_split_raw = int(os.environ.get("SPLIT_MINUTES", "60"))
SPLIT_MINUTES = _split_raw if _split_raw > 0 else None


def run_git(*args, check=True):
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=check, capture_output=True, text=True
    )


def commit_and_push(reason: str):
    build_dashboard_feed.main()

    run_git("add", "docs/data/")
    diff = run_git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return  # nothing new since the last cycle

    run_git("commit", "-m", f"Update lightning data ({reason}) {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")

    for attempt in range(1, 6):
        push = run_git("push", check=False)
        if push.returncode == 0:
            print(f"  committed + pushed ({reason})")
            break
        # Most likely cause: the PREVIOUS job (still winding down during
        # the deliberate handoff overlap) pushed a commit in between.
        # Merge rather than rebase, with -X ours: each job's own CSV file
        # has a unique, timestamped name, so two jobs' CSVs never actually
        # conflict (git merges two different new files trivially) -- the
        # only file that CAN conflict is docs/data/pagasa_lightning_latest.json,
        # since both jobs regenerate that same path every cycle. -X ours
        # auto-resolves any such conflict by keeping OUR just-regenerated
        # copy, with no manual conflict markers and no risk to the CSVs
        # (a plain `git reset --hard` here would risk deleting the CSV
        # this job is still actively writing to, which is exactly what
        # this avoids).
        print(f"  push rejected (attempt {attempt}/5), merging and retrying: {push.stderr.strip()}")
        run_git("pull", "--no-rebase", "-X", "ours", "--no-edit", check=False)
        time.sleep(3)
    else:
        print("  WARNING: couldn't push after 5 attempts -- will try again next cycle")

    _sync_to_drive()


def _sync_to_drive():
    # Reuses upload_to_drive.py's own main(), which already no-ops cleanly
    # if the GDRIVE_* secrets aren't set -- so this is safe to call every
    # cycle whether or not Drive sync is configured.
    try:
        import upload_to_drive

        upload_to_drive.main()
    except Exception as e:
        print(f"  [Drive sync error, will retry next cycle] {e}")


watch_error = {}


def run_watch(stop_event: threading.Event):
    try:
        if SOURCE == "panahon":
            core.watch_lightning_panahon(OUTDIR, stop_event=stop_event, split_minutes=SPLIT_MINUTES)
        else:
            core.watch_lightning(OUTDIR, interval=60, stop_event=stop_event, split_minutes=SPLIT_MINUTES)
    except Exception as e:
        watch_error["error"] = e
        watch_error["traceback"] = traceback.format_exc()
        stop_event.set()  # unblock the main loop below immediately


def main():
    run_git("config", "user.name", "github-actions[bot]")
    run_git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")

    print(
        f"Starting continuous watch (source={SOURCE}), self-stopping after "
        f"{MAX_RUNTIME_SECONDS / 3600:.1f}h, committing every "
        f"{COMMIT_INTERVAL_SECONDS / 60:.0f} min."
    )

    stop_event = threading.Event()
    watch_thread = threading.Thread(target=run_watch, args=(stop_event,), daemon=True)
    watch_thread.start()

    poll_step = min(COMMIT_INTERVAL_SECONDS, 10)
    start = time.time()
    last_commit = start
    while True:
        time.sleep(poll_step)
        now = time.time()
        elapsed = now - start

        if not watch_thread.is_alive():
            # The watch thread died (an exception, or it already honored a
            # stop_event we didn't set -- shouldn't normally happen before
            # we ask it to). Either way, stop looping uselessly.
            break

        # A simple elapsed-time check rather than a modulo trick -- robust
        # to real sleep() drift, which a "does elapsed land exactly on a
        # multiple of the interval" check would not be.
        if now - last_commit >= COMMIT_INTERVAL_SECONDS:
            commit_and_push("periodic")
            last_commit = now

        if elapsed >= MAX_RUNTIME_SECONDS:
            print("Reached self-imposed max runtime -- stopping gracefully for handoff to the next scheduled run.")
            break

    stop_event.set()
    watch_thread.join(timeout=30)

    if "error" in watch_error:
        print(f"\nWatch thread ended with an error: {watch_error['error']}")
        print(watch_error["traceback"])

    commit_and_push("final")
    print("Done for this job -- the next scheduled run will continue watching.")


if __name__ == "__main__":
    main()
