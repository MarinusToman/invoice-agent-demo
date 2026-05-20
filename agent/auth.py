import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # read + mark as read (superset of gmail.readonly)
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]

CREDENTIALS_DIR = Path(__file__).parent.parent / "credentials"
CLIENT_SECRET = CREDENTIALS_DIR / "client_secret.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"


def get_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials not found at {CLIENT_SECRET}\n"
                    "Follow Section 5 of the tutorial to download client_secret.json "
                    "from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            print("\nA browser window will open. Sign in and click 'Allow'.")
            print("Once you see 'The authentication flow has completed', return here.\n")
            creds = flow.run_local_server(port=8080, open_browser=True)

        TOKEN_FILE.write_text(creds.to_json())
        print(f"Google credentials saved to {TOKEN_FILE}")

    return creds


def get_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds)


def get_sheets_service(creds: Credentials):
    return build("sheets", "v4", credentials=creds)


def get_services() -> dict:
    creds = get_credentials()
    return {
        "gmail": get_gmail_service(creds),
        "sheets": get_sheets_service(creds),
    }


if __name__ == "__main__":
    print("Authorizing Google access...")
    services = get_services()
    print("Authorization successful. You can now run the agent.")
