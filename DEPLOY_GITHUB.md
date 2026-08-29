# Running the lightning watch on GitHub (free, no server to manage)

This runs `radar_to_tiff.py`'s pagasa lightning source on a schedule using
GitHub Actions, publishes a live dashboard via GitHub Pages, and (if you
set it up) copies the data into your own Google Drive -- all without any
computer of yours needing to be on, and without any VM/SSH/systemd.

**Why pagasa and not panahon:** GitHub Actions can't keep a process alive
indefinitely (every job is killed at 6 hours no matter what, and schedule
triggers are best-effort, not exact). So instead of one long-running watch,
this wakes up every ~15 minutes, does one quick fetch, and exits. That
fits pagasa's REST snapshot perfectly. It does *not* fit panahon's live
push feed -- a connection that only lasts a few seconds every 15 minutes
would miss almost everything, the same way your PC being off missed the
11 PM-12 AM window. If you want panahon's richer data later, that still
needs something that stays connected continuously (the earlier VM-based
option from before).

## 1. Create the repo

1. Go to <https://github.com/new>. Name it anything (e.g.
   `pagasa-lightning-watch`). **Keep it Public.**

   Why public matters here, concretely: GitHub Actions on public repos is
   unlimited/free. Private repos get a 2,000-minutes/month free budget --
   and at a 15-minute interval, this workflow runs ~96 times/day. Even at
   just 1 minute per run, that's already ~2,880 minutes/month, over the
   private free allowance. Public sidesteps that entirely; there's nothing
   sensitive in this repo (just lightning coordinates and a public
   script), so public is the right default here.

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

The workflow is already scheduled (every 15 min) the moment it's pushed --
you don't need to do anything else for the GitHub side to start working.
To confirm it right away instead of waiting:

Repo -> **Actions** tab -> **Lightning watch** (left sidebar) -> **Run
workflow** button -> **Run workflow**. After ~30-60 seconds, refresh --
you should see a green checkmark, and a new commit appear in the repo
under `docs/data/`. Reload your Pages URL and the dashboard should now
show real data.

From here it just keeps running on its own schedule, forever, whether
your computer or anything else is on.

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
both files updated there automatically. No further sign-in ever needed;
the refresh token keeps working indefinitely unless you revoke it.

## Checking on it later

- **Dashboard:** `https://YOUR_USERNAME.github.io/YOUR_REPO/`
- **Run history / errors:** repo -> **Actions** tab -> **Lightning watch**
  -> click any run to see its logs.
- **Raw data:** `docs/data/pagasa_lightning_log.csv` (full history) and
  `docs/data/pagasa_lightning_latest.json` (recent + stats) in the repo
  itself, or in your Drive's PAGASA_Lightning folder if you set that up.

## Changing settings later

To change the interval, edit the `cron:` line in
`.github/workflows/lightning-watch.yml` (cron syntax: minute hour day
month weekday, all in UTC) and push the change -- it takes effect on the
next scheduled tick, nothing to restart.

## If a run fails

Click the failed run in the Actions tab to see exactly what errored.
`poll_and_commit.py` is written to not crash the whole workflow if PAGASA
itself has a transient hiccup (a timeout, a 5xx) -- it just logs it and
leaves existing data untouched, so a single bad run doesn't lose anything;
the next scheduled run 15 minutes later tries again automatically.
