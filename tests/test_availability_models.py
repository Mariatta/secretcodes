from zoneinfo import ZoneInfo

import pytest
from django.db import connection

from availability.models import (
    AvailabilityProfile,
    GoogleAccount,
    TrackedCalendar,
    _default_business_hours,
    _default_extended_hours,
)


@pytest.mark.django_db
def test_google_account_str():
    account = GoogleAccount.objects.create(label="work", email="a@b.com")
    assert str(account) == "work <a@b.com>"


@pytest.mark.django_db
def test_google_account_refresh_token_is_encrypted_at_rest():
    account = GoogleAccount.objects.create(
        label="enc", email="enc@b.com", refresh_token="super-secret"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT refresh_token FROM availability_googleaccount WHERE id = %s",
            [account.id],
        )
        stored = cursor.fetchone()[0]
    assert stored != "super-secret"
    assert len(stored) > len("super-secret")
    reloaded = GoogleAccount.objects.get(pk=account.pk)
    assert reloaded.refresh_token == "super-secret"


@pytest.mark.django_db
def test_google_account_blank_refresh_token_stays_blank():
    account = GoogleAccount.objects.create(label="blank", email="blank@b.com")
    reloaded = GoogleAccount.objects.get(pk=account.pk)
    assert reloaded.refresh_token == ""


@pytest.mark.django_db
def test_base_model_save_preserves_update_fields():
    account = GoogleAccount.objects.create(label="u", email="u@b.com")
    account.label = "updated"
    account.save(update_fields=["label"])
    reloaded = GoogleAccount.objects.get(pk=account.pk)
    assert reloaded.label == "updated"


@pytest.mark.django_db
def test_base_model_save_default_path_updates_modified_date():
    account = GoogleAccount.objects.create(label="m", email="m@b.com")
    original = account.modified_date
    account.label = "changed"
    account.save()
    assert account.modified_date >= original


@pytest.mark.django_db
def test_tracked_calendar_str():
    account = GoogleAccount.objects.create(label="x", email="x@b.com")
    cal = TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
    )
    assert str(cal) == "Primary"


@pytest.mark.django_db
def test_tracked_calendar_related_name():
    account = GoogleAccount.objects.create(label="r", email="r@b.com")
    TrackedCalendar.objects.create(
        account=account, google_calendar_id="c1", display_label="A"
    )
    TrackedCalendar.objects.create(
        account=account, google_calendar_id="c2", display_label="B"
    )
    assert account.tracked_calendars.count() == 2


@pytest.mark.django_db
def test_availability_profile_str():
    profile = AvailabilityProfile.get_solo()
    assert "AvailabilityProfile" in str(profile)
    assert "America/Vancouver" in str(profile)


@pytest.mark.django_db
def test_availability_profile_is_singleton():
    first = AvailabilityProfile.get_solo()
    first.timezone = ZoneInfo("UTC")
    first.save()
    second = AvailabilityProfile.get_solo()
    assert second.pk == 1
    assert second.timezone == ZoneInfo("UTC")
    assert AvailabilityProfile.objects.count() == 1


@pytest.mark.django_db
def test_availability_profile_timezone_is_zoneinfo():
    profile = AvailabilityProfile.get_solo()
    assert isinstance(profile.timezone, ZoneInfo)


@pytest.mark.django_db
def test_availability_profile_defaults_from_brief():
    profile = AvailabilityProfile.get_solo()
    assert profile.timezone == ZoneInfo("America/Vancouver")
    assert profile.default_slot_minutes == 30
    assert profile.min_notice_hours == 12
    assert profile.max_horizon_days == 21
    assert profile.extended_reveal_threshold == 4
    assert profile.meeting_buffer_minutes == 30


def test_default_business_hours_shape():
    hours = _default_business_hours()
    assert set(hours) == {"mon", "tue", "wed", "thu", "fri"}
    assert hours["mon"] == [["09:00", "17:00"]]


def test_default_extended_hours_shape():
    hours = _default_extended_hours()
    assert hours["mon"] == [["08:00", "09:00"], ["17:00", "19:00"]]
