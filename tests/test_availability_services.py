from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from availability.services.availability import (
    AvailabilityResult,
    BusyBlock,
    FreeSlot,
    _overlaps_any_busy,
    _parse_hhmm,
    compute_availability,
)

UTC = ZoneInfo("UTC")
PT = ZoneInfo("America/Vancouver")


@dataclass
class FakeProfile:
    timezone: ZoneInfo = PT
    business_hours: dict = None
    extended_hours: dict = None
    default_slot_minutes: int = 30

    def __post_init__(self):
        if self.business_hours is None:
            self.business_hours = {
                d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri")
            }
        if self.extended_hours is None:
            self.extended_hours = {
                d: [["08:00", "09:00"], ["17:00", "19:00"]]
                for d in ("mon", "tue", "wed", "thu", "fri")
            }


def _pt(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=PT)


def test_parse_hhmm_roundtrip():
    parsed = _parse_hhmm("09:30")
    assert parsed.hour == 9 and parsed.minute == 30


def test_overlaps_any_busy_detects_overlap():
    block = BusyBlock(_pt(2026, 5, 4, 10), _pt(2026, 5, 4, 11))
    assert _overlaps_any_busy(_pt(2026, 5, 4, 10, 30), _pt(2026, 5, 4, 11, 0), [block])


def test_overlaps_any_busy_no_overlap_when_adjacent():
    block = BusyBlock(_pt(2026, 5, 4, 10), _pt(2026, 5, 4, 11))
    assert not _overlaps_any_busy(_pt(2026, 5, 4, 11), _pt(2026, 5, 4, 11, 30), [block])


def test_overlaps_any_busy_empty_list():
    assert not _overlaps_any_busy(_pt(2026, 5, 4, 10), _pt(2026, 5, 4, 11), [])


def test_empty_result_when_range_inverted():
    result = compute_availability(
        _pt(2026, 5, 4, 17), _pt(2026, 5, 4, 9), [], FakeProfile()
    )
    assert result == AvailabilityResult()


def test_full_business_day_has_sixteen_slots():
    result = compute_availability(
        _pt(2026, 5, 4, 0), _pt(2026, 5, 5, 0), [], FakeProfile()
    )
    assert result.business_slot_count == 16
    assert all(s.band == "business" for s in result.free_slots)
    assert len(result.free_slots) == 16


def test_busy_block_removes_overlapping_slots():
    busy = [BusyBlock(_pt(2026, 5, 4, 10, 15), _pt(2026, 5, 4, 10, 45))]
    result = compute_availability(
        _pt(2026, 5, 4, 0), _pt(2026, 5, 5, 0), busy, FakeProfile()
    )
    assert result.business_slot_count == 14
    slot_starts = {s.start.hour * 60 + s.start.minute for s in result.free_slots}
    assert 10 * 60 not in slot_starts and 10 * 60 + 30 not in slot_starts


def test_weekend_excluded_by_default():
    saturday = _pt(2026, 5, 9, 0)
    result = compute_availability(
        saturday, saturday + timedelta(days=1), [], FakeProfile()
    )
    assert result.free_slots == []
    assert result.business_slot_count == 0


def test_extended_band_returned_only_when_requested():
    monday = _pt(2026, 5, 4, 0)
    without = compute_availability(
        monday, monday + timedelta(days=1), [], FakeProfile()
    )
    with_ext = compute_availability(
        monday, monday + timedelta(days=1), [], FakeProfile(), include_extended=True
    )
    assert without.business_slot_count == with_ext.business_slot_count == 16
    assert any(s.band == "extended" for s in with_ext.free_slots)
    assert not any(s.band == "extended" for s in without.free_slots)


def test_extended_slots_counted_separately_from_business():
    monday = _pt(2026, 5, 4, 0)
    result = compute_availability(
        monday, monday + timedelta(days=1), [], FakeProfile(), include_extended=True
    )
    extended = [s for s in result.free_slots if s.band == "extended"]
    # 08:00-09:00 = 2 slots, 17:00-19:00 = 4 slots → 6 total
    assert len(extended) == 6
    assert result.business_slot_count == 16


def test_default_slot_duration_from_profile():
    profile = FakeProfile(default_slot_minutes=60)
    result = compute_availability(_pt(2026, 5, 4, 0), _pt(2026, 5, 5, 0), [], profile)
    assert result.business_slot_count == 8


def test_duration_override_argument_wins():
    result = compute_availability(
        _pt(2026, 5, 4, 0),
        _pt(2026, 5, 5, 0),
        [],
        FakeProfile(),
        duration=timedelta(hours=1),
    )
    assert result.business_slot_count == 8


def test_slots_clipped_to_requested_range():
    result = compute_availability(
        _pt(2026, 5, 4, 11), _pt(2026, 5, 4, 14), [], FakeProfile()
    )
    assert result.business_slot_count == 6
    assert all(_pt(2026, 5, 4, 11) <= s.start for s in result.free_slots)
    assert all(s.end <= _pt(2026, 5, 4, 14) for s in result.free_slots)


def test_crossing_timezone_classifies_in_profile_tz():
    profile = FakeProfile()
    # UTC 16:00-17:00 Monday == PT 09:00-10:00 (business hour start)
    result = compute_availability(
        datetime(2026, 5, 4, 16, 0, tzinfo=UTC),
        datetime(2026, 5, 4, 17, 0, tzinfo=UTC),
        [],
        profile,
    )
    assert result.business_slot_count == 2
    assert result.free_slots[0].band == "business"


def test_free_slots_sorted_chronologically():
    monday = _pt(2026, 5, 4, 0)
    tuesday = monday + timedelta(days=1)
    result = compute_availability(
        monday, tuesday + timedelta(days=1), [], FakeProfile(), include_extended=True
    )
    starts = [s.start for s in result.free_slots]
    assert starts == sorted(starts)


def test_freeslot_dataclass_is_immutable():
    slot = FreeSlot(_pt(2026, 5, 4, 9), _pt(2026, 5, 4, 9, 30), "business")
    with pytest.raises(Exception):
        slot.band = "extended"
