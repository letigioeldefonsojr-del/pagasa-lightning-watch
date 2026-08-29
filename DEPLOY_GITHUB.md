# Running the lightning watch on GitHub (free, no server to manage)

This runs `radar_to_tiff.py`'s **real, continuous** lightning watch
(`watch_lightning_panahon()` by default -- the same live push-feed watcher
built into the desktop tool) inside a GitHub Actions job, publishes a live
dashboard via GitHub Pages, and (if you set it up) copies the data into
your own Google Drive -- all without any computer of yours needing to be
on, and without any VM/SSH/systemd.

## Why this is genuinely close to real-time (not a 15-minute poll)

GitHub Actions can't keep a job running forever -- every job is hard-killed
at 6 hours no matter what, and `schedule:` triggers are best-effort (they
can slip a few minutes under load, not guaranteed to the second). An
earlier version of this design worked around that by waking up every 15
minutes, fetching once, and exiting -- but that's not actually real-time,
and if PAGASA's own rolling window is shorter than 15 minutes (it isn't
publicly documented, so this can't be assumed), strikes in between fetches
would be missed entirely.

This version does it properly instead: each scheduled job runs your
**actual** continuous watch function -- the same one the desktop GUI/CLI
uses -- for as long as it's allowed to:

- **panahon** (the default): a live Socket.IO connection that stays open
  and receives each strike the moment it's pushed, exactly like running
  `radar_to_tiff.py --lightning-panahon-watch` on your own PC.
- **pagasa**: the REST source, polled every 60 seconds continuously for
  the whole job (not once every 15 minutes).

Each job self-stops after **~5h50m** -- comfortably under GitHub's 6-hour
hard kill -- so it always gets a clean final commit instead of being cut
off mid-write. The workflow is scheduled every **5 hours**, so the next
job starts about **50 minutes before** the previous one's self-imposed
stop time. That overlap is deliberate: it exists to absorb GitHub's
schedule being best-effort, so even if a run starts a bit late, there's
still a live watcher connected the whole time. The two overlapping jobs
each write to their own uniquely-named data file and push independently;
this has been tested repeatedly under real concurrent-push conditions
(including forced push conflicts) with no data loss in any run.

Net effect: as long as GitHub actually fires each scheduled run
(it's best-effort, so treat "always" as "almost always" -- see
**If a run fails** below), there should be no real gap in coverage, and
strikes show up on the dashboard within a few minutes of happening, not
up to 15 minutes late.

## 1. Create the repo

1. Go to <https://github.com/new>. Name it anything (e.g.
   `pagasa-lightning-watch`). **Keep it Public.**

   Why public matters here, concretely: GitHub Actions on public repos is
   unlimited/free. Private repos get a 2,000-minutes/month free budget --
   and this workflow now runs for up to ~5h50m at a time, multiple times a
   day, which would blow well past that private-repo budget almost
   immediately. Public sidesteps that entirely; there's nothing sensitive
   in this repo (just lightning coordinates and a public script), so
   public is the right default here.

2. Don't initialize it with a README/gitignore -- you're pushing existing
   files, so an empty repo is easiest.

## 2. Push these files

From inside this `github-hosted` folder on your own computer:

```
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

(If you don't have `git` installed or aren't comfortable with the command
line yet, GitHub's web UI also lets you drag-and-drop this whole folder in
via "Add file -> Upload files" on the repo's page -- just make sure the
folder structure, especially the `.github/workflows/` path, is preserved.)

## 3. Turn on GitHub Pages

Repo -> **Settings -> Pages**. Under "Build and deployment", set **Source:
Deploy from a branch**, **Branch: main**, folder **/docs**. Save.

GitHub will give you a URL like
`https://YOUR_USERNAME.github.io/YOUR_REPO/` -- that's your live
dashboard, though it'll show "No strikes logged yet" until the first
scheduled run completes (next step).

## 4. Let it run

The workflow is already scheduled (every 5 hours) the moment it's pushed
-- you don't need to do anything else for the GitHub side to start
working. To confirm it right away instead of waiting:

Repo -> **Actions** tab -> **Lightning watch** (left sidebar) -> **Run
workflow** button -> **Run workflow**. It'll keep running for as long as
there's lightning activity to watch (up to ~5h50m) -- you don't need to
wait for it to finish. After a minute or two, refresh -- you should see
the run in progress, and a new commit appear in the repo under
`docs/data/` (it commits every 5 minutes while running, not just at the
end). Reload your Pages URL and the dashboard should now show real data.

From here it just keeps running on its own schedule, forever, whether
your computer or anything else is on -- each job watching continuously
until it hands off to the next one.

## 5. (Optional) One-time Google Drive setup

If you want the data copied into your Drive too, do this once:

### Create an OAuth client (a few clicks, free, no card needed for this)

1. Go to <https://console.cloud.google.com/>, create a new project (any
   name).
2. **APIs & Services -> Library**, search **Google Drive API**, click
   **Enable**.
3. **APIs & Services -> OAuth consent screen**: choose **External**, fill
   in an app name (anything) and your email in the two email fields, save
   through the steps. When it asks about test users, add your own Google
   account's email as a test user. You don't need to submit for
   verification -- test mode works fine for just you.
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client
   ID**. Application type: **Desktop app**. Name it anything. Click
   Create -- it shows you a **Client ID** and **Client Secret**. Copy both.

### Get your refresh token (once, on your own computer)

```
pip install requests
python scripts/get_drive_refresh_token.py YOUR_CLIENT_ID YOUR_CLIENT_SECRET
```

This opens your browser, asks you to approve access to your Drive
(you'll see a Google warning that the app is unverified -- that's normal
for a personal project in test mode; click **Advanced -> Go to (app
name), unsafe** to proceed, since it's your own app). It then prints three
values.

### Add the secrets to GitHub

Repo -> **Settings -> Secrets and variables -> Actions -> New repository
secret**. Add all three, exactly as printed:

- `GDRIVE_CLIENT_ID`
- `GDRIVE_CLIENT_SECRET`
- `GDRIVE_REFRESH_TOKEN`

That's it -- the next scheduled run (or manually run one from the Actions
tab) will create a **PAGASA_Lightning** folder in your own Drive and keep
it updated automatically, every 5 minutes while a job is running. No
further sign-in ever needed; the refresh token keeps working indefinitely
unless you revoke it.

## Checking on it later

- **Dashboard:** `https://YOUR_USERNAME.github.io/YOUR_REPO/`
- **Run history / errors:** repo -> **Actions** tab -> **Lightning watch**
  -> click any run to see its logs (it streams live output the whole time
  a job is running, so you can watch strikes come in in real time there
  too).
- **Raw data:** `docs/data/` in the repo holds one CSV per job run (each
  named with that run's own start time -- e.g.
  `panahon_lightning_split60min_...csv` -- so files never collide between
  overlapping jobs) plus `docs/data/pagasa_lightning_latest.json`, which
  is the merged, deduplicated feed the dashboard actually reads. All of it
  is also mirrored into your Drive's PAGASA_Lightning folder if you set
  that up.

## Changing settings later

`.github/workflows/lightning-watch.yml` has three things you can tune,
each takes effect on the next scheduled run (nothing to restart):

- **`LIGHTNING_SOURCE`**: `panahon` (default, live push feed, richer
  per-strike data) or `pagasa` (simpler REST polling, no extra Python
  dependency).
- **`cron:`** how often a new job starts (cron syntax: minute hour day
  month weekday, all in UTC). If you change this, also reconsider
  `MAX_RUNTIME_SECONDS` below so the two stay in the "next job starts
  before the previous one's self-imposed stop" relationship described
  above -- shortening the interval without shortening the runtime just
  means more overlap (harmless, just more redundant runtime), but
  lengthening the interval past `MAX_RUNTIME_SECONDS` reopens a real gap.
- **`MAX_RUNTIME_SECONDS`**: how long each job watches before stopping
  itself gracefully. Keep it comfortably under 21600 (6 hours = GitHub's
  hard kill); the default 21000 (5h50m) leaves 10 minutes of margin for a
  clean final commit.

## If a run fails

Click the failed run in the Actions tab to see exactly what errored. If
the watch connection drops or errors out, `watch_and_commit.py` still
commits and pushes whatever was collected before stopping -- so a bad run
doesn't lose what it already had, and the *next* scheduled run (at most 5
hours later) reconnects and continues automatically. The main thing
outside this script's control is GitHub itself occasionally skipping or
delaying a scheduled trigger under high platform load, which is why the
job overlap described above exists -- it's the mitigation for exactly
that risk, not a guarantee it can never happen.
