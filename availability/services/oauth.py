import requests
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def build_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        autogenerate_code_verifier=True,
    )


def fetch_user_email(credentials) -> str:
    service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    return service.userinfo().get().execute()["email"]


def revoke_token(token: str) -> bool:
    """Revoke an OAuth token at Google.

    Returns True when Google confirms the revocation OR when the token was
    already invalid (so callers can treat both as "no longer accessible").
    Returns False on network errors or unexpected failures so the caller
    can decide whether to proceed.
    """
    if not token:
        return True
    try:
        resp = requests.post(
            GOOGLE_REVOKE_URL,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
    except requests.RequestException:
        return False
    if resp.status_code == 200:
        return True
    if resp.status_code == 400:
        try:
            return resp.json().get("error") == "invalid_token"
        except ValueError:
            return False
    return False
