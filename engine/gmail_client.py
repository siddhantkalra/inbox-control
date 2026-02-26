from __future__ import annotations

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from config import CREDENTIALS_PATH, TOKEN_READONLY_PATH, TOKEN_MODIFY_PATH

SCOPES_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_MODIFY = ["https://www.googleapis.com/auth/gmail.modify"]


def _get_service(scopes: list[str], token_path):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing credentials.json at {CREDENTIALS_PATH}. "
                    "Download OAuth Desktop credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def get_gmail_service_readonly():
    return _get_service(SCOPES_READONLY, TOKEN_READONLY_PATH)


def get_gmail_service_modify():
    return _get_service(SCOPES_MODIFY, TOKEN_MODIFY_PATH)
