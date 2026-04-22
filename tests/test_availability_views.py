import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.urls import reverse

from availability.models import AvailabilityProfile
from availability.services.availability import BusyBlock
from availability.views import _display_range


@pytest.mark.django_db
def test_week_grid_renders(client):
    response = client.get(reverse("availability:week_grid"))
    assert response.status_code == 200
    assert b"Mariatta's availability" in response.content


@pytest.mark.django_db
def test_week_grid_defaults_to_summary_view(client):
    response = client.get(reverse("availability:week_grid"))
    assert b"Recommended" in response.content or b"Wide open" in response.content


@pytest.mark.django_db
def test_week_grid_detail_view_shows_slot_badges(client):
    response = client.get(reverse("availability:week_grid") + "?view=detail")
    assert b"bg-success" in response.content


@pytest.mark.django_db
def test_week_grid_renders_extended_when_toggled(client):
    response = client.get(reverse("availability:week_grid") + "?include_extended=true")
    assert response.status_code == 200


@pytest.mark.django_db
def test_week_grid_shows_exhaustion_cta_when_below_threshold(client):
    with patch("availability.views.compute_availability") as mock_compute:
        mock_compute.return_value = type(
            "R", (), {"free_slots": [], "business_slot_count": 0}
        )
        response = client.get(reverse("availability:week_grid") + "?view=detail")
    assert b"Need a different time?" in response.content


@pytest.mark.django_db
def test_week_grid_summary_renders_no_slots_message(client):
    with patch("availability.views.compute_availability") as mock_compute:
        mock_compute.return_value = type(
            "R", (), {"free_slots": [], "business_slot_count": 0}
        )
        response = client.get(reverse("availability:week_grid") + "?view=detail")
    assert b"No free slots" in response.content


@pytest.mark.django_db
def test_landing_page_links_to_availability(client):
    response = client.get(reverse("index"))
    assert response.status_code == 200
    assert reverse("availability:week_grid").encode() in response.content


def _slots_url(**params):
    return reverse("availability:slots_json") + "?" + urlencode(params)


@pytest.mark.django_db
def test_slots_json_returns_structured_slots(client):
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
        )
    )
    assert response.status_code == 200
    data = response.json()
    assert "slots" in data and "business_slot_count" in data
    assert isinstance(data["slots"], list)
    for slot in data["slots"]:
        assert set(slot) == {"start", "end", "band"}


@pytest.mark.django_db
def test_slots_json_respects_duration_param(client):
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
            duration=60,
        )
    )
    data = response.json()
    assert data["business_slot_count"] == 8


@pytest.mark.django_db
def test_slots_json_respects_include_extended(client):
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
            include_extended="true",
        )
    )
    data = response.json()
    assert any(slot["band"] == "extended" for slot in data["slots"])


@pytest.mark.django_db
def test_check_endpoint_free_during_business_hours(client):
    candidate = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc).isoformat()
    response = client.post(
        reverse("availability:check"),
        data=json.dumps({"datetime": candidate, "duration": 30}),
        content_type="application/json",
    )
    data = response.json()
    assert data["free"] is True
    assert data["band"] == "business"


@pytest.mark.django_db
def test_check_endpoint_not_free_on_weekend(client):
    candidate = datetime(2026, 5, 9, 17, 0, tzinfo=timezone.utc).isoformat()
    response = client.post(
        reverse("availability:check"),
        data=json.dumps({"datetime": candidate, "duration": 30}),
        content_type="application/json",
    )
    data = response.json()
    assert data["free"] is False
    assert data["reason"]


@pytest.mark.django_db
def test_check_endpoint_defaults_duration_to_thirty(client):
    candidate = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc).isoformat()
    response = client.post(
        reverse("availability:check"),
        data=json.dumps({"datetime": candidate}),
        content_type="application/json",
    )
    data = response.json()
    assert data["free"] is True


@pytest.mark.django_db
def test_display_range_starts_today_in_profile_tz():
    wednesday = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
    with patch("availability.views.timezone.now", return_value=wednesday):
        start, end = _display_range(AvailabilityProfile.get_solo())
    assert start.weekday() == 2
    assert start.hour == 0 and start.minute == 0
    assert (end - start) == timedelta(days=14)


@pytest.mark.django_db
def test_week_grid_uses_real_busy_blocks_from_google(client):
    monday_10 = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)
    monday_17 = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc)
    busy = [BusyBlock(monday_10, monday_17)]
    with patch(
        "availability.views.fetch_busy_blocks_for_all", return_value=busy
    ) as mock_fetch:
        response = client.get(reverse("availability:week_grid"))
    assert response.status_code == 200
    mock_fetch.assert_called_once()


@pytest.mark.django_db
def test_slots_json_uses_real_busy_blocks(client):
    # 17:00-18:00 UTC = 10:00-11:00 PDT (inside 9-5 PT business hours)
    busy_start = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc)
    busy_end = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    busy = [BusyBlock(busy_start, busy_end)]
    with patch("availability.views.fetch_busy_blocks_for_all", return_value=busy):
        response = client.get(
            _slots_url(
                start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
                end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
            )
        )
    data = response.json()
    # Without busy: 16 business slots; with 10-11 busy, 2 slots removed
    assert data["business_slot_count"] == 14


@pytest.mark.django_db
def test_check_endpoint_reports_busy(client):
    candidate_start = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc)
    candidate_end = datetime(2026, 5, 4, 17, 30, tzinfo=timezone.utc)
    busy = [BusyBlock(candidate_start, candidate_end)]
    with patch("availability.views.fetch_busy_blocks_for_all", return_value=busy):
        response = client.post(
            reverse("availability:check"),
            data=json.dumps({"datetime": candidate_start.isoformat(), "duration": 30}),
            content_type="application/json",
        )
    data = response.json()
    assert data["free"] is False
    assert data["reason"] == "Busy"
