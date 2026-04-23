from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Optional


class Band(StrEnum):
    BUSINESS = "business"
    EXTENDED = "extended"


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"

    @classmethod
    def from_date(cls, d) -> "Weekday":
        return list(cls)[d.weekday()]


class DayLabel(StrEnum):
    def __new__(cls, value: str, headline: str, rank: int) -> "DayLabel":
        member = str.__new__(cls, value)
        member._value_ = value
        member.headline = headline
        member.rank = rank
        return member

    WIDE_OPEN = ("wide_open", "Available", 4)
    LIKELY_AVAILABLE = ("likely_available", "Likely available", 3)
    TIGHT = ("tight", "Tight but possible", 2)
    UNLIKELY = ("unlikely", "Unlikely", 1)
    FULLY_BOOKED = ("fully_booked", "Unavailable", 0)


@dataclass(frozen=True)
class BusyBlock:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class FreeSlot:
    start: datetime
    end: datetime
    band: Band


@dataclass(frozen=True)
class AvailabilityResult:
    free_slots: list[FreeSlot] = field(default_factory=list)
    business_slot_count: int = 0


@dataclass(frozen=True)
class DayRecommendation:
    date: date_type
    label: DayLabel
    reason: str
    free_minutes: int
    business_minutes: int
    meeting_count: int
    best_window: Optional[tuple[datetime, datetime]]


@dataclass(frozen=True)
class WeekRecommendation:
    days: list[DayRecommendation] = field(default_factory=list)
    best: Optional[DayRecommendation] = None


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def _windows_for_day(
    profile_hours: dict[str, list[list[str]]], weekday_key: str
) -> list[tuple[time, time]]:
    raw = profile_hours.get(weekday_key, [])
    return [(_parse_hhmm(start), _parse_hhmm(end)) for start, end in raw]


def _overlaps_any_busy(
    slot_start: datetime, slot_end: datetime, busy_blocks: list[BusyBlock]
) -> bool:
    return any(
        max(slot_start, block.start) < min(slot_end, block.end) for block in busy_blocks
    )


def _generate_slots_in_window(
    day: datetime,
    window: tuple[time, time],
    duration: timedelta,
    busy_blocks: list[BusyBlock],
    band: Band,
    range_start: datetime,
    range_end: datetime,
) -> list[FreeSlot]:
    tz = day.tzinfo
    window_start = datetime.combine(day.date(), window[0], tzinfo=tz)
    window_end = datetime.combine(day.date(), window[1], tzinfo=tz)
    slots: list[FreeSlot] = []
    cursor = window_start
    while cursor + duration <= window_end:
        slot_end = cursor + duration
        if (
            cursor >= range_start
            and slot_end <= range_end
            and not _overlaps_any_busy(cursor, slot_end, busy_blocks)
        ):
            slots.append(FreeSlot(start=cursor, end=slot_end, band=band))
        cursor = slot_end
    return slots


def _apply_buffer(busy_blocks: list[BusyBlock], buffer: timedelta) -> list[BusyBlock]:
    """Pad every busy block by ±buffer so adjacent meetings get breathing room."""
    if not buffer:
        return busy_blocks
    return [
        BusyBlock(start=block.start - buffer, end=block.end + buffer)
        for block in busy_blocks
    ]


def compute_availability(
    range_start: datetime,
    range_end: datetime,
    busy_blocks: list[BusyBlock],
    profile,
    duration: timedelta | None = None,
    include_extended: bool = False,
    buffer: timedelta = timedelta(),
) -> AvailabilityResult:
    if range_start >= range_end:
        return AvailabilityResult()

    tz = profile.timezone
    if duration is None:
        duration = timedelta(minutes=profile.default_slot_minutes)

    padded_busy = _apply_buffer(busy_blocks, buffer)

    local_start = range_start.astimezone(tz)
    local_end = range_end.astimezone(tz)

    free_slots: list[FreeSlot] = []
    business_count = 0

    day = datetime.combine(local_start.date(), time.min, tzinfo=tz)
    last_day = datetime.combine(local_end.date(), time.min, tzinfo=tz)
    while day <= last_day:
        weekday_key = Weekday.from_date(day)

        for window in _windows_for_day(profile.business_hours, weekday_key):
            slots = _generate_slots_in_window(
                day,
                window,
                duration,
                padded_busy,
                Band.BUSINESS,
                range_start,
                range_end,
            )
            free_slots.extend(slots)
            business_count += len(slots)

        if include_extended:
            for window in _windows_for_day(profile.extended_hours, weekday_key):
                slots = _generate_slots_in_window(
                    day,
                    window,
                    duration,
                    padded_busy,
                    Band.EXTENDED,
                    range_start,
                    range_end,
                )
                free_slots.extend(slots)

        day += timedelta(days=1)

    free_slots.sort(key=lambda slot: slot.start)
    return AvailabilityResult(free_slots=free_slots, business_slot_count=business_count)


def classify_candidate(
    profile,
    candidate_start: datetime,
    candidate_end: datetime,
    busy_blocks: list[BusyBlock],
    buffer: timedelta = timedelta(),
) -> tuple[bool, Band | None, str | None]:
    if candidate_end <= candidate_start:
        return False, None, "End must be after start"

    tz = profile.timezone
    local_start = candidate_start.astimezone(tz)
    local_end = candidate_end.astimezone(tz)

    if local_start.date() != local_end.date():
        return False, None, "Spans multiple days"

    padded_busy = _apply_buffer(busy_blocks, buffer)
    if _overlaps_any_busy(candidate_start, candidate_end, padded_busy):
        return False, None, "Busy"

    weekday_key = Weekday.from_date(local_start)

    for win_start, win_end in _windows_for_day(profile.business_hours, weekday_key):
        if local_start.time() >= win_start and local_end.time() <= win_end:
            return True, Band.BUSINESS, None

    for win_start, win_end in _windows_for_day(profile.extended_hours, weekday_key):
        if local_start.time() >= win_start and local_end.time() <= win_end:
            return True, Band.EXTENDED, None

    return False, None, "Outside business/extended hours"


def _business_minutes_for_weekday(profile, weekday_key: str) -> int:
    total = 0
    for start_str, end_str in profile.business_hours.get(weekday_key, []):
        start = _parse_hhmm(start_str)
        end = _parse_hhmm(end_str)
        total += (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return total


def _longest_free_stretch(
    slots: list[FreeSlot],
) -> Optional[tuple[datetime, datetime]]:
    if not slots:
        return None
    best_start, best_end = slots[0].start, slots[0].end
    run_start, run_end = slots[0].start, slots[0].end
    for slot in slots[1:]:
        if slot.start == run_end:
            run_end = slot.end
        else:
            if (run_end - run_start) > (best_end - best_start):
                best_start, best_end = run_start, run_end
            run_start, run_end = slot.start, slot.end
    if (run_end - run_start) > (best_end - best_start):
        best_start, best_end = run_start, run_end
    return (best_start, best_end)


def score_day(
    day: date_type,
    slots_for_day: list[FreeSlot],
    busy_for_day: list[BusyBlock],
    profile,
) -> DayRecommendation:
    weekday_key = Weekday.from_date(day)
    business_minutes = _business_minutes_for_weekday(profile, weekday_key)

    business_slots = [s for s in slots_for_day if s.band == Band.BUSINESS]
    free_minutes = sum(
        int((s.end - s.start).total_seconds() // 60) for s in business_slots
    )
    meeting_count = len(busy_for_day)

    if business_minutes == 0:
        label = DayLabel.FULLY_BOOKED
        reason = "Outside business hours"
    else:
        free_ratio = free_minutes / business_minutes
        if free_ratio >= 0.9:
            label = DayLabel.WIDE_OPEN
        elif free_ratio >= 0.5:
            label = DayLabel.LIKELY_AVAILABLE
        elif free_ratio >= 0.2:
            label = DayLabel.TIGHT
        elif free_ratio > 0:
            label = DayLabel.UNLIKELY
        else:
            label = DayLabel.FULLY_BOOKED
        suffix = "s" if meeting_count != 1 else ""
        reason = f"{meeting_count} other meeting{suffix}"

    return DayRecommendation(
        date=day,
        label=label,
        reason=reason,
        free_minutes=free_minutes,
        business_minutes=business_minutes,
        meeting_count=meeting_count,
        best_window=_longest_free_stretch(business_slots),
    )


def recommend_week(
    result: AvailabilityResult,
    busy_blocks: list[BusyBlock],
    profile,
    range_start: datetime,
    range_end: datetime,
) -> WeekRecommendation:
    tz = profile.timezone
    slots_by_date: dict[date_type, list[FreeSlot]] = defaultdict(list)
    for slot in result.free_slots:
        slots_by_date[slot.start.astimezone(tz).date()].append(slot)

    busy_by_date: dict[date_type, list[BusyBlock]] = defaultdict(list)
    for block in busy_blocks:
        busy_by_date[block.start.astimezone(tz).date()].append(block)

    start_date = range_start.astimezone(tz).date()
    end_date = range_end.astimezone(tz).date()

    days: list[DayRecommendation] = []
    cursor = start_date
    while cursor < end_date:
        days.append(
            score_day(cursor, slots_by_date[cursor], busy_by_date[cursor], profile)
        )
        cursor += timedelta(days=1)

    available = [d for d in days if d.label is not DayLabel.FULLY_BOOKED]
    best = (
        max(available, key=lambda d: (d.label.rank, d.free_minutes))
        if available
        else None
    )
    return WeekRecommendation(days=days, best=best)
