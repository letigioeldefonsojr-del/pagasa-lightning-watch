#!/usr/bin/env python3
"""Uploads/updates the lightning CSV + JSON in your own Google Drive,
authenticating AS YOU via a stored OAuth refresh token -- not a service
account.

Why not a service account (the "normal" way people automate Drive from a
script): a service account has its own, essentially empty Drive storage
quota that's completely separate from your personal account's quota, even
when it's uploading into a folder you've shared with it. Uploads from a
service account into a personal (non-Google-Workspace) Drive fail with
"The user's Drive storage quota has been exceeded" -- a very commonly hit
dead end, confirmed by checking multiple real reports of exactly this
error before building it this way. A refresh token obtained via a normal
one-time sign-in as your own account sidesteps that entirely: uploads
then count against, and appear directly in, your own Drive, same as if
you'd dragged the file in yourself.

Requires three environment variables (set as GitHub Actions secrets --
see DEPLOY_GITHUB.md for how to get these):
    GDRIVE_CLIENT_ID
    GDRIVE_CLIENT_SECRET
    GDRIVE_REFRESH_TOKEN
"""
import json
import os
import sys
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_FOLDER_NAME = "PAGASA_Lightning"
DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
# There's no single canonical CSV anymore -- each job run writes its own
# uniquely-timestamped segment file (see scripts/build_dashboard_feed.py,
# which uses this same glob to merge them for the dashboard). Sync every
# segment that exists locally, plus the merged JSON feed.
CSV_GLOBS = ["pagasa_lightning_*.csv", "panahon_lightning_*.csv"]
JSON_FILE = "pagasa_lightning_latest.json"


def get_access_token() -> str:
    client_id = os.environ["GDRIVE_CLIENT_ID"]
    client_secret = os.environ["GDRIVE_CLIENT_SECRET"]
    refresh_token = os.environ["GDRIVE_REFRESH_TOKEN"]
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Couldn't refresh the Google Drive access token ({resp.status_code}): "
            f"{resp.text}\n\nMost likely cause: the refresh token was revoked (e.g. "
            "you removed this app's access at https://myaccount.google.com/permissions) "
            "or one of the three GDRIVE_* secrets is wrong -- rerun "
            "get_drive_refresh_token.py to get a fresh one."
        )
    return resp.json()["access_token"]


def find_or_create_folder(token: str, name: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    resp = requests.get(
        DRIVE_FILES_URL, headers=headers, params={"q": q, "fields": "files(id,name)"}, timeout=30
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    if files:
        return files[0]["id"]
    resp = requests.post(
        DRIVE_FILES_URL,
        headers=headers,
        json={"name": name, "mimeType": "application/vnd.google-apps.folder"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def find_file(token: str, name: str, parent_id: str):
    headers = {"Authorization": f"Bearer {token}"}
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    resp = requests.get(
        DRIVE_FILES_URL, headers=headers, params={"q": q, "fields": "files(id,name)"}, timeout=30
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def upload_or_update(token: str, local_path: Path, parent_id: str, mime_type: str):
    headers = {"Authorization": f"Bearer {token}"}
    existing_id = find_file(token, local_path.name, parent_id)
    content = local_path.read_bytes()

    if existing_id:
        resp = requests.patch(
            f"{DRIVE_UPLOAD_URL}/{existing_id}?uploadType=media",
            headers={**headers, "Content-Type": mime_type},
            data=content,
            timeout=60,
        )
        resp.raise_for_status()
        print(f"  updated {local_path.name} (Drive file {existing_id})")
    else:
        boundary = "radarlightningboundary"
        metadata = {"name": local_path.name, "parents": [parent_id]}
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--".encode("utf-8")
        resp = requests.post(
            f"{DRIVE_UPLOAD_URL}?uploadType=multipart",
            headers={**headers, "Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
            timeout=60,
        )
        resp.raise_for_status()
        print(f"  created {local_path.name} (Drive file {resp.json().get('id')})")


def main():
    missing = [k for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        print(f"Skipping Drive upload -- missing secret(s): {', '.join(missing)}")
        return

    token = get_access_token()
    folder_id = find_or_create_folder(token, DRIVE_FOLDER_NAME)
    print(f"Syncing to Drive folder '{DRIVE_FOLDER_NAME}' ({folder_id}):")

    mime_by_ext = {".csv": "text/csv", ".json": "application/json"}
    csv_paths = sorted(set(p for pattern in CSV_GLOBS for p in DATA_DIR.glob(pattern)))
    json_path = DATA_DIR / JSON_FILE
    paths = csv_paths + ([json_path] if json_path.exists() else [])
    if not paths:
        print("  nothing to sync yet")
        return
    for path in paths:
        upload_or_update(token, path, folder_id, mime_by_ext.get(path.suffix, "application/octet-stream"))


if __name__ == "__main__":
    main()
