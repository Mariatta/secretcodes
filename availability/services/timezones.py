"""Viewer timezone helpers for the availability page.

The page is rendered in the viewer's timezone, which arrives as a ``tz``
query parameter: either an IANA zone name or one of the city aliases below.
"""

from datetime import UTC, datetime, tzinfo
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


def _offsets_through_a_year(name: str) -> tuple:
    """A zone's UTC offset in January and July, to tell two zones apart."""
    zone = ZoneInfo(name)
    return tuple(
        datetime(2026, month, 1, tzinfo=UTC).astimezone(zone).utcoffset()
        for month in (1, 7)
    )


@lru_cache(maxsize=1)
def _zone_names_by_city() -> dict[str, str]:
    """Zone names keyed by their city part ("lisbon" for Europe/Lisbon).

    Several names for the same clock count as one city: Europe/Istanbul and
    Asia/Istanbul both answer to "istanbul". A city whose zones keep
    different time is left out, because picking one for the visitor would be
    a guess. The Etc/ zones are left out too: their signs are inverted, so
    "GMT+5" would land five hours behind UTC, not ahead.
    """
    by_city: dict[str, list[str]] = {}
    for lowered, name in _zone_names_by_lowercase().items():
        if not name.startswith("Etc/"):
            by_city.setdefault(lowered.rsplit("/", 1)[-1], []).append(name)
    return {
        city: max(names, key=lambda name: (len(name), name))
        for city, names in by_city.items()
        if len({_offsets_through_a_year(name) for name in names}) == 1
    }


def resolve_timezone(value: str) -> ZoneInfo | None:
    """Turn what a visitor typed into a timezone, or None when it is unknown.

    Accepts an IANA name in any letter case ("europe/lisbon"), with spaces
    in place of underscores ("America/New York"), a city alias ("seattle"),
    or just the city part of a zone name ("lisbon").
    """
    wanted = " ".join(value.lower().split())
    if not wanted:
        return None
    wanted = CITY_ALIASES.get(wanted, wanted).lower().replace(" ", "_")
    name = _zone_names_by_lowercase().get(wanted) or _zone_names_by_city().get(wanted)
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
