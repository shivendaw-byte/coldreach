"""Standalone Gmail draft creation (no Claude required).

One-time setup:
  1. console.cloud.google.com -> new project -> enable the Gmail API
  2. OAuth consent screen -> External -> add sdawda@sas.upenn.edu as a test user
  3. Credentials -> OAuth client ID -> Desktop app -> download as credentials.json
     into this project folder
  4. python -m coldreach push      (browser opens once; token.json is cached)

Scope is gmail.compose: this can create drafts. It cannot send, read, or delete mail.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
CREDS = ROOT / "credentials.json"
TOKEN = ROOT / "token.json"


def service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise SystemExit("pip install google-api-python-client google-auth-oauthlib")

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS.exists():
                raise SystemExit(f"Missing {CREDS}. See the setup notes in gmail_api.py.")
            creds = InstalledAppFlow.from_client_secrets_file(
                str(CREDS), SCOPES).run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def create_draft(svc, sender: str, to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg.set_content(body)                    # text/plain, utf-8 — never HTML
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    created = svc.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}).execute()
    return created["id"]
