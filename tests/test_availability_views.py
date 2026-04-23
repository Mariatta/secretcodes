import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.urls import reverse

from availability.models import AvailabilityProfile, GoogleAccount, TrackedCalendar
from availability.services.availability import BusyBlock
from availability.services.google import has_active_calendars
from availability.views import _display_range


@pytest.mark.django_db
def test_week_grid_renders(client):
    response = client.get(reverse("availability:week_grid"))
    assert response.status_code == 200
    assert b"Mariatta's availability" in response.content


@pytest.mark.django_db
def test_week_grid_shows_check_back_later_when_disconnected(client, monkeypatch):
    monkeypatch.setattr("availability.views.has_active_calendars", lambda: False)
    response = client.get(reverse("availability:week_grid"))
    assert response.status_code == 200
    assert b"No live calendar data yet" in response.content
    assert b"check back later" in response.content
    assert b"Recommended" not in response.content


@pytest.mark.django_db
def test_has_active_calendars_true_when_account_has_active_tracked_calendar():
    account = GoogleAccount.objects.create(
        label="real", email="real@example.com", refresh_token="r-real"
    )
    TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
        is_active=True,
    )
    assert has_active_calendars() is True


@pytest.mark.django_db
def test_has_active_calendars_false_when_no_accounts():
    assert has_active_calendars() is False


@pytest.mark.django_db
def test_has_active_calendars_false_when_account_token_empty():
    account = GoogleAccount.objects.create(
        label="blank", email="blank@example.com", refresh_token=""
    )
    TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
        is_active=True,
    )
    assert has_active_calendars() is False


@pytest.mark.django_db
def test_has_active_calendars_false_when_only_inactive_calendars():
    account = GoogleAccount.objects.create(
        label="r", email="r@example.com", refresh_token="r"
    )
    TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
        is_active=False,
    )
    assert has_active_calendars() is False


@pytest.mark.django_db
def test_slots_json_when_disconnected_returns_empty(client, monkeypatch):
    monkeypatch.setattr("availability.views.has_active_calendars", lambda: False)
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
        )
    )
    data = response.json()
    assert data["connected"] is False
    assert data["slots"] == []
    assert data["business_slot_count"] == 0


@pytest.mark.django_db
def test_slots_json_when_connected_includes_connected_true(client):
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
        )
    )
    assert response.json()["connected"] is True


@pytest.mark.django_db
def test_check_when_disconnected_returns_connected_false(client, monkeypatch):
    monkeypatch.setattr("availability.views.has_active_calendars", lambda: False)
    candidate = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc).isoformat()
    response = client.post(
        reverse("availability:check"),
        data=json.dumps({"datetime": candidate}),
        content_type="application/json",
    )
    data = response.json()
    assert data["connected"] is False
    assert data["free"] is None
    assert data["band"] is None
    assert data["reason"] == "No calendars connected"


@pytest.mark.django_db
def test_check_when_connected_includes_connected_true(client):
    candidate = datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc).isoformat()
    response = client.post(
        reverse("availability:check"),
        data=json.dumps({"datetime": candidate}),
        content_type="application/json",
    )
    assert response.json()["connected"] is True


@pytest.mark.django_db
def test_slots_json_rejects_range_exceeding_max(client):
    response = client.get(
        _slots_url(
            start=datetime(2026, 5, 4, 0, tzinfo=timezone.utc).isoformat(),
            end=datetime(2026, 5, 25, 0, tzinfo=timezone.utc).isoformat(),
        )
    )
    assert response.status_code == 400
    assert "14 days" in response.json()["error"]


@pytest.mark.django_db
def test_slots_json_rate_limits(client, settings):
    settings.AVAILABILITY_API_RATE_LIMIT = "2/m"
    url = _slots_url(
        start=datetime(2026, 5, 4, 0, tzinfo=timezone.utc).isoformat(),
        end=datetime(2026, 5, 5, 0, tzinfo=timezone.utc).isoformat(),
    )
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    response = client.get(url)
    assert response.status_code == 429
    assert response.json() == {"error": "Rate limit exceeded"}


@pytest.mark.django_db
def test_check_endpoint_rate_limits(client, settings):
    settings.AVAILABILITY_API_RATE_LIMIT = "2/m"
    body = json.dumps(
        {"datetime": datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc).isoformat()}
    )
    url = reverse("availability:check")
    assert (
        client.post(url, data=body, content_type="application/json").status_code == 200
    )
    assert (
        client.post(url, data=body, content_type="application/json").status_code == 200
    )
    response = client.post(url, data=body, content_type="application/json")
    assert response.status_code == 429


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
    # 17:00-18:00 UTC = 10:00-11:00 PDT (inside 9-5 PT business hours).
    # With the default 30-min meeting buffer, the busy block pads to
    # 9:30-11:30 PDT, eating 4 of the 16 business slots (9:30-10:00,
    # 10:00-10:30, 10:30-11:00, 11:00-11:30).
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
    assert data["business_slot_count"] == 12


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
