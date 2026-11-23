"""Viewer timezone helpers for the availability page.

The page is rendered in the viewer's timezone, which arrives as a ``tz``
query parameter: either an IANA zone name or one of the city aliases below.
"""

from datetime import datetime, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

CITY_ALIASES = {
    "seattle": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "salt lake city": "America/Denver",
    "austin": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "boston": "America/New_York",
    "washington": "America/New_York",
    "pittsburgh": "America/New_York",
    "philadelphia": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "montreal": "America/Toronto",
    "ottawa": "America/Toronto",
    "calgary": "America/Edmonton",
    "victoria": "America/Vancouver",
    "rio de janeiro": "America/Sao_Paulo",
    "edinburgh": "Europe/London",
    "manchester": "Europe/London",
    "porto": "Europe/Lisbon",
    "barcelona": "Europe/Madrid",
    "munich": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "hamburg": "Europe/Berlin",
    "milan": "Europe/Rome",
    "florence": "Europe/Rome",
    "geneva": "Europe/Zurich",
    "krakow": "Europe/Warsaw",
    "cape town": "Africa/Johannesburg",
    "abu dhabi": "Asia/Dubai",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "beijing": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "bandung": "Asia/Jakarta",
    "surabaya": "Asia/Jakarta",
    "bali": "Asia/Makassar",
    "osaka": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "canberra": "Australia/Sydney",
    "wellington": "Pacific/Auckland",
}


@lru_cache(maxsize=1)
def _zone_names_by_lowercase() -> dict[str, str]:
    """Every IANA zone name this server knows, keyed by its lowercase form."""
    return {name.lower(): name for name in available_timezones()}


def resolve_timezone(value: str) -> ZoneInfo | None:
    """Turn what a visitor typed into a timezone, or None when it is unknown.

    Accepts an IANA name in any letter case ("europe/lisbon"), with spaces
    in place of underscores ("America/New York"), or a city alias
    ("seattle").
    """
    wanted = " ".join(value.lower().split())
    if not wanted:
        return None
    wanted = CITY_ALIASES.get(wanted, wanted).lower().replace(" ", "_")
    name = _zone_names_by_lowercase().get(wanted)
    return ZoneInfo(name) if name else None


def aliases_by_zone() -> dict[str, list[str]]:
    """City aliases grouped by the zone they point at, for the type-in field."""
    grouped: dict[str, list[str]] = {}
    for city, zone in CITY_ALIASES.items():
        grouped.setdefault(zone, []).append(city.title())
    return grouped


def describe_offset(display_tz: tzinfo, host_tz: tzinfo, moment: datetime) -> str:
    """Say how far ``display_tz`` is from ``host_tz`` at ``moment``.

    Returns a phrase that reads naturally before a name, such as
    "9 hours ahead of" or "3 hours 30 min behind", and an empty string when
    both zones show the same time.
    """
    difference = (
        moment.astimezone(display_tz).utcoffset()
        - moment.astimezone(host_tz).utcoffset()
    )
    minutes = int(difference.total_seconds() // 60)
    if minutes == 0:
        return ""
    hours, rest = divmod(abs(minutes), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'' if hours == 1 else 's'}")
    if rest:
        parts.append(f"{rest} min")
    direction = "ahead of" if minutes > 0 else "behind"
    return f"{' '.join(parts)} {direction}"
