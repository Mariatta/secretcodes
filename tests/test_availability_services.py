from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from availability.services.availability import (
    AvailabilityResult,
    BusyBlock,
    FreeSlot,
    WeekRecommendation,
    _longest_free_stretch,
    _overlaps_any_busy,
    _parse_hhmm,
    classify_candidate,
    compute_availability,
    recommend_week,
    score_day,
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


def test_classify_candidate_business_hours():
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 4, 10), _pt(2026, 5, 4, 10, 30), []
    )
    assert free is True and band == "business" and reason is None


def test_classify_candidate_extended_hours():
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 4, 8, 15), _pt(2026, 5, 4, 8, 45), []
    )
    assert free is True and band == "extended" and reason is None


def test_classify_candidate_weekend():
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 9, 10), _pt(2026, 5, 9, 10, 30), []
    )
    assert free is False and band is None
    assert "Outside" in reason


def test_classify_candidate_busy():
    busy = [BusyBlock(_pt(2026, 5, 4, 10), _pt(2026, 5, 4, 11))]
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 4, 10, 15), _pt(2026, 5, 4, 10, 45), busy
    )
    assert free is False and reason == "Busy"


def test_classify_candidate_inverted_range():
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 4, 10, 30), _pt(2026, 5, 4, 10), []
    )
    assert free is False and "End" in reason


def test_classify_candidate_spans_multiple_days():
    free, band, reason = classify_candidate(
        FakeProfile(), _pt(2026, 5, 4, 23), _pt(2026, 5, 5, 1), []
    )
    assert free is False and "multiple" in reason


def _slot(start_hour, start_min, end_hour, end_min, band="business"):
    return FreeSlot(
        _pt(2026, 5, 4, start_hour, start_min),
        _pt(2026, 5, 4, end_hour, end_min),
        band,
    )


def test_longest_free_stretch_none_when_empty():
    assert _longest_free_stretch([]) is None


def test_longest_free_stretch_merges_adjacent():
    slots = [_slot(9, 0, 9, 30), _slot(9, 30, 10, 0), _slot(11, 0, 11, 30)]
    start, end = _longest_free_stretch(slots)
    assert start == _pt(2026, 5, 4, 9, 0)
    assert end == _pt(2026, 5, 4, 10, 0)


def test_longest_free_stretch_picks_trailing_run():
    slots = [_slot(9, 0, 9, 30), _slot(13, 0, 14, 0), _slot(14, 0, 15, 0)]
    start, end = _longest_free_stretch(slots)
    assert start == _pt(2026, 5, 4, 13)
    assert end == _pt(2026, 5, 4, 15)


def test_score_day_wide_open_with_no_meetings():
    full_day_slots = [_slot(h, 0, h, 30) for h in range(9, 17)] + [
        _slot(h, 30, h + 1, 0) for h in range(9, 17)
    ]
    rec = score_day(_pt(2026, 5, 4).date(), full_day_slots, [], FakeProfile())
    assert rec.label == "wide_open"
    assert rec.label.headline == "Available"
    assert rec.meeting_count == 0
    assert rec.reason == "0 other meetings"
    assert rec.free_minutes == 480
    assert rec.business_minutes == 480
    assert rec.best_window is not None


def test_score_day_likely_available():
    half_day = [_slot(h, 0, h, 30) for h in range(9, 13)] + [
        _slot(h, 30, h + 1, 0) for h in range(9, 13)
    ]
    rec = score_day(_pt(2026, 5, 4).date(), half_day, [], FakeProfile())
    assert rec.label == "likely_available"


def test_score_day_tight():
    # Four slots = 120 min of 480 = 25%, lands in tight (0.2-0.5)
    few_slots = [
        _slot(9, 0, 9, 30),
        _slot(9, 30, 10, 0),
        _slot(13, 0, 13, 30),
        _slot(13, 30, 14, 0),
    ]
    rec = score_day(_pt(2026, 5, 4).date(), few_slots, [], FakeProfile())
    assert rec.label == "tight"


def test_score_day_unlikely():
    one_slot = [_slot(9, 0, 9, 30)]
    rec = score_day(_pt(2026, 5, 4).date(), one_slot, [], FakeProfile())
    assert rec.label == "unlikely"


def test_score_day_fully_booked_when_no_slots():
    rec = score_day(_pt(2026, 5, 4).date(), [], [], FakeProfile())
    assert rec.label == "fully_booked"


def test_score_day_weekend_is_fully_booked():
    rec = score_day(_pt(2026, 5, 9).date(), [], [], FakeProfile())
    assert rec.label == "fully_booked"
    assert "business hours" in rec.reason.lower()


def test_score_day_counts_meetings_in_reason():
    one_slot = [_slot(9, 0, 9, 30)]
    busy = [BusyBlock(_pt(2026, 5, 4, 10), _pt(2026, 5, 4, 11))]
    rec = score_day(_pt(2026, 5, 4).date(), one_slot, busy, FakeProfile())
    assert rec.meeting_count == 1
    assert rec.reason == "1 other meeting"


def test_recommend_week_picks_best_day():
    monday = _pt(2026, 5, 4, 0)
    friday = _pt(2026, 5, 9, 0)
    result = compute_availability(monday, friday, [], FakeProfile())
    week = recommend_week(result, [], FakeProfile(), monday, friday)
    assert isinstance(week, WeekRecommendation)
    assert week.best is not None
    assert week.best.label == "wide_open"
    assert len(week.days) == 5


def test_recommend_week_best_none_when_all_weekend():
    saturday = _pt(2026, 5, 9, 0)
    monday_after = _pt(2026, 5, 11, 0)
    result = compute_availability(saturday, monday_after, [], FakeProfile())
    week = recommend_week(result, [], FakeProfile(), saturday, monday_after)
    assert week.best is None
    assert all(d.label == "fully_booked" for d in week.days)


def test_recommend_week_groups_busy_blocks_by_date():
    monday = _pt(2026, 5, 4, 0)
    friday = _pt(2026, 5, 9, 0)
    busy = [BusyBlock(_pt(2026, 5, 5, 10), _pt(2026, 5, 5, 11))]
    result = compute_availability(monday, friday, busy, FakeProfile())
    week = recommend_week(result, busy, FakeProfile(), monday, friday)
    tuesday = next(d for d in week.days if d.date == _pt(2026, 5, 5).date())
    assert tuesday.meeting_count == 1
