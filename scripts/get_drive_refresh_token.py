#!/usr/bin/env python3
"""Run this ONCE on your own computer (never on GitHub) to get a Google
Drive refresh token for upload_to_drive.py.

This opens your browser, asks you to sign in and approve access to your
own Google Drive, then prints three values to paste into your GitHub
repo's secrets. You only need to do this once -- the refresh token keeps
working indefinitely (until you revoke it), so the GitHub Actions workflow
can keep using it forever without you signing in again.

Before running this you need a free Google OAuth "Desktop app" client ID
+ secret -- see the "One-time Google Drive setup" section in
DEPLOY_GITHUB.md for exactly how to create one (a few clicks in Google
Cloud Console, no cost, no card required for this part).

Usage:
    pip install requests
    python get_drive_refresh_token.py YOUR_CLIENT_ID YOUR_CLIENT_SECRET
"""
import http.server
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser

import requests

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"
REDIRECT_PORT = 8721
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"


def main():
    if len(sys.argv) != 3:
        print("Usage: python get_drive_refresh_token.py CLIENT_ID CLIENT_SECRET")
        sys.exit(1)
    client_id, client_secret = sys.argv[1], sys.argv[2]

    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            code_holder["code"] = params.get("code", [None])[0]
            code_holder["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body>Done -- you can close this tab and go back to your terminal.</body></html>"
            )

        def log_message(self, *a):
            pass

    server = socketserver.TCPServer(("localhost", REDIRECT_PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # forces a refresh_token even if you've approved this before
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Opening your browser to sign in and approve access...")
    print(f"If it doesn't open automatically, visit this URL:\n{url}\n")
    webbrowser.open(url)

    for _ in range(120):
        if code_holder:
            break
        time.sleep(1)
    else:
        print("Timed out waiting for you to approve access -- run this again.")
        sys.exit(1)

    if code_holder.get("error"):
        print(f"Google returned an error: {code_holder['error']}")
        sys.exit(1)

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code_holder["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print(
            "No refresh_token came back -- Google only sends one the first time you "
            "approve an app, or when you force re-consent.\n"
            "Fix: go to https://myaccount.google.com/permissions, remove access for "
            "this app (it'll be named after your Google Cloud project), then run this "
            "script again."
        )
        sys.exit(1)

    print("\nSuccess. Add these three values as GitHub repo secrets:")
    print("(repo -> Settings -> Secrets and variables -> Actions -> New repository secret)\n")
    print(f"  GDRIVE_CLIENT_ID     = {client_id}")
    print(f"  GDRIVE_CLIENT_SECRET = {client_secret}")
    print(f"  GDRIVE_REFRESH_TOKEN = {refresh_token}")
    print(
        "\nKeep that refresh token private -- anyone who has it can upload files to "
        "the Drive folder it's scoped to (drive.file scope: only files this app "
        "creates, not your whole Drive). GitHub secrets are encrypted and never shown "
        "in logs, so pasting it there is safe."
    )


if __name__ == "__main__":
    main()
