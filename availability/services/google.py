from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from availability.models import GoogleAccount

from .availability import BusyBlock

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _cache_key(account, range_start: datetime, range_end: datetime) -> str:
    return (
        f"availability:busy:{account.pk}:"
        f"{range_start.isoformat()}:{range_end.isoformat()}"
    )


def _build_credentials(account) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=account.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=list(account.scopes_granted or []),
    )


def _parse_freebusy_response(response: dict) -> list[BusyBlock]:
    blocks: list[BusyBlock] = []
    for calendar_data in response.get("calendars", {}).values():
        for entry in calendar_data.get("busy", []):
            blocks.append(
                BusyBlock(
                    start=datetime.fromisoformat(entry["start"]),
                    end=datetime.fromisoformat(entry["end"]),
                )
            )
    blocks.sort(key=lambda b: b.start)
    return blocks


def fetch_busy_blocks(
    account, range_start: datetime, range_end: datetime
) -> list[BusyBlock]:
    if not account.refresh_token:
        return []
    tracked = list(account.tracked_calendars.filter(is_active=True))
    if not tracked:
        return []

    key = _cache_key(account, range_start, range_end)
    cached = cache.get(key)
    if cached is not None:
        return cached

    credentials = _build_credentials(account)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    body = {
        "timeMin": range_start.isoformat(),
        "timeMax": range_end.isoformat(),
        "items": [{"id": c.google_calendar_id} for c in tracked],
    }
    response = service.freebusy().query(body=body).execute()

    blocks = _parse_freebusy_response(response)
    cache.set(key, blocks, timeout=settings.GOOGLE_FREEBUSY_CACHE_SECONDS)
    return blocks


def fetch_busy_blocks_for_all(
    range_start: datetime, range_end: datetime
) -> list[BusyBlock]:
    blocks: list[BusyBlock] = []
    for account in GoogleAccount.objects.all():
        blocks.extend(fetch_busy_blocks(account, range_start, range_end))
    blocks.sort(key=lambda b: b.start)
    return blocks


def has_active_calendars() -> bool:
    """Whether at least one connected account has an active tracked calendar.

    When this returns False, the availability views should not display a
    fabricated "all free" schedule — there's simply no data yet.
    """
    return (
        GoogleAccount.objects.exclude(refresh_token="")
        .filter(tracked_calendars__is_active=True)
        .exists()
    )
