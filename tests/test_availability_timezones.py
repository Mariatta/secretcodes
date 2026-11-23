from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from availability.services.timezones import (
    CITY_ALIASES,
    aliases_by_zone,
    describe_offset,
    resolve_timezone,
)

UTC = ZoneInfo("UTC")
NOVEMBER = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("Europe/Lisbon", "Europe/Lisbon"),
        ("europe/lisbon", "Europe/Lisbon"),
        ("  America/New York ", "America/New_York"),
        ("UTC", "UTC"),
        ("seattle", "America/Los_Angeles"),
        ("San  Francisco", "America/Los_Angeles"),
        ("Lisbon", "Europe/Lisbon"),
        ("tokyo", "Asia/Tokyo"),
        ("los angeles", "America/Los_Angeles"),
    ],
)
def test_resolve_timezone_accepts_zone_names_and_cities(typed, expected):
    assert resolve_timezone(typed) == ZoneInfo(expected)


@pytest.mark.parametrize("typed", ["", "   ", "Atlantis", "../etc/passwd"])
def test_resolve_timezone_returns_none_for_unknown(typed):
    assert resolve_timezone(typed) is None


def test_resolve_timezone_does_not_guess_between_zones_sharing_a_city():
    """Buenos Aires names both America/Buenos_Aires and the Argentina/ zone."""
    assert resolve_timezone("Buenos Aires") is None
    assert resolve_timezone("America/Argentina/Buenos_Aires") is not None


def test_every_city_alias_points_at_a_real_timezone():
    for city, zone in CITY_ALIASES.items():
        assert resolve_timezone(city) == ZoneInfo(zone), city


def test_aliases_by_zone_groups_title_cased_cities():
    grouped = aliases_by_zone()
    assert "Seattle" in grouped["America/Los_Angeles"]
    assert "San Francisco" in grouped["America/Los_Angeles"]
    assert grouped["Europe/Lisbon"] == ["Porto"]


@pytest.mark.parametrize(
    "zone, expected",
    [
        ("UTC", ""),
        ("Africa/Abidjan", ""),
        ("Asia/Tokyo", "9 hours ahead of"),
        ("Africa/Lagos", "1 hour ahead of"),
        ("Asia/Kolkata", "5 hours 30 min ahead of"),
        ("Pacific/Honolulu", "10 hours behind"),
        ("Pacific/Marquesas", "9 hours 30 min behind"),
    ],
)
def test_describe_offset(zone, expected):
    """Measured against UTC, using zones with no daylight saving changes."""
    assert describe_offset(ZoneInfo(zone), UTC, NOVEMBER) == expected


def test_describe_offset_under_an_hour():
    """Kathmandu (+5:45) is 15 minutes ahead of Kolkata (+5:30)."""
    kathmandu = ZoneInfo("Asia/Kathmandu")
    kolkata = ZoneInfo("Asia/Kolkata")
    assert describe_offset(kathmandu, kolkata, NOVEMBER) == "15 min ahead of"
