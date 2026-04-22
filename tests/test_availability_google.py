from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from availability.models import GoogleAccount, TrackedCalendar
from availability.services.availability import BusyBlock
from availability.services.google import (
    _build_credentials,
    _cache_key,
    _parse_freebusy_response,
    fetch_busy_blocks,
    fetch_busy_blocks_for_all,
)

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_account(**kwargs):
    defaults = dict(
        label="personal",
        email="a@example.com",
        refresh_token="refresh-xyz",
        scopes_granted=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    defaults.update(kwargs)
    return GoogleAccount.objects.create(**defaults)


def _add_calendar(account, google_calendar_id="primary"):
    return TrackedCalendar.objects.create(
        account=account,
        google_calendar_id=google_calendar_id,
        display_label=google_calendar_id,
        is_active=True,
    )


def _range():
    return (
        datetime(2026, 5, 4, 0, tzinfo=UTC),
        datetime(2026, 5, 5, 0, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_fetch_returns_empty_when_no_refresh_token():
    account = _make_account(refresh_token="")
    _add_calendar(account)
    assert fetch_busy_blocks(account, *_range()) == []


@pytest.mark.django_db
def test_fetch_returns_empty_when_no_tracked_calendars():
    account = _make_account()
    assert fetch_busy_blocks(account, *_range()) == []


@pytest.mark.django_db
def test_fetch_returns_empty_when_only_inactive_calendars():
    account = _make_account()
    TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
        is_active=False,
    )
    assert fetch_busy_blocks(account, *_range()) == []


@pytest.mark.django_db
def test_fetch_calls_freebusy_with_tracked_calendar_ids():
    account = _make_account()
    _add_calendar(account, "primary")
    _add_calendar(account, "other@group.calendar.google.com")

    service = MagicMock()
    service.freebusy().query().execute.return_value = {"calendars": {}}

    with patch("availability.services.google.build", return_value=service):
        fetch_busy_blocks(account, *_range())

    request_body = service.freebusy.return_value.query.call_args.kwargs["body"]
    ids = [item["id"] for item in request_body["items"]]
    assert set(ids) == {"primary", "other@group.calendar.google.com"}


@pytest.mark.django_db
def test_fetch_parses_busy_blocks_from_response():
    account = _make_account()
    _add_calendar(account)

    service = MagicMock()
    service.freebusy().query().execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {
                        "start": "2026-05-04T10:00:00+00:00",
                        "end": "2026-05-04T11:00:00+00:00",
                    }
                ]
            }
        }
    }

    with patch("availability.services.google.build", return_value=service):
        blocks = fetch_busy_blocks(account, *_range())

    assert blocks == [
        BusyBlock(
            datetime(2026, 5, 4, 10, tzinfo=UTC),
            datetime(2026, 5, 4, 11, tzinfo=UTC),
        )
    ]


@pytest.mark.django_db
def test_fetch_aggregates_and_sorts_across_calendars():
    account = _make_account()
    _add_calendar(account, "primary")
    _add_calendar(account, "work")

    service = MagicMock()
    service.freebusy().query().execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {
                        "start": "2026-05-04T14:00:00+00:00",
                        "end": "2026-05-04T15:00:00+00:00",
                    }
                ]
            },
            "work": {
                "busy": [
                    {
                        "start": "2026-05-04T09:00:00+00:00",
                        "end": "2026-05-04T10:00:00+00:00",
                    }
                ]
            },
        }
    }

    with patch("availability.services.google.build", return_value=service):
        blocks = fetch_busy_blocks(account, *_range())

    assert len(blocks) == 2
    assert blocks[0].start < blocks[1].start


@pytest.mark.django_db
def test_fetch_caches_result_and_skips_second_api_call():
    account = _make_account()
    _add_calendar(account)

    service = MagicMock()
    service.freebusy().query().execute.return_value = {"calendars": {}}

    with patch(
        "availability.services.google.build", return_value=service
    ) as mock_build:
        fetch_busy_blocks(account, *_range())
        fetch_busy_blocks(account, *_range())

    assert mock_build.call_count == 1


@pytest.mark.django_db
def test_fetch_busy_blocks_for_all_aggregates_across_accounts():
    acc1 = _make_account(email="a1@example.com")
    acc2 = _make_account(email="a2@example.com")
    _add_calendar(acc1)
    _add_calendar(acc2)

    service = MagicMock()
    service.freebusy().query().execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {
                        "start": "2026-05-04T10:00:00+00:00",
                        "end": "2026-05-04T11:00:00+00:00",
                    }
                ]
            }
        }
    }

    with patch("availability.services.google.build", return_value=service):
        blocks = fetch_busy_blocks_for_all(*_range())

    assert len(blocks) == 2


@override_settings(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="csecret")
@pytest.mark.django_db
def test_build_credentials_uses_refresh_token_and_client_settings():
    account = _make_account(refresh_token="r-abc")
    credentials = _build_credentials(account)
    assert credentials.refresh_token == "r-abc"
    assert credentials.client_id == "cid"
    assert credentials.client_secret == "csecret"


@pytest.mark.django_db
def test_cache_key_unique_per_account_and_range():
    a1 = _make_account(email="a1@example.com")
    a2 = _make_account(email="a2@example.com")
    start, end = _range()
    assert _cache_key(a1, start, end) != _cache_key(a2, start, end)


def test_parse_freebusy_response_handles_empty():
    assert _parse_freebusy_response({}) == []
    assert _parse_freebusy_response({"calendars": {}}) == []
    assert _parse_freebusy_response({"calendars": {"x": {}}}) == []
