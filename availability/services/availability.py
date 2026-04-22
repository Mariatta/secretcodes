from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal

Band = Literal["business", "extended"]

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


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


def compute_availability(
    range_start: datetime,
    range_end: datetime,
    busy_blocks: list[BusyBlock],
    profile,
    duration: timedelta | None = None,
    include_extended: bool = False,
) -> AvailabilityResult:
    if range_start >= range_end:
        return AvailabilityResult()

    tz = profile.timezone
    if duration is None:
        duration = timedelta(minutes=profile.default_slot_minutes)

    local_start = range_start.astimezone(tz)
    local_end = range_end.astimezone(tz)

    free_slots: list[FreeSlot] = []
    business_count = 0

    day = datetime.combine(local_start.date(), time.min, tzinfo=tz)
    last_day = datetime.combine(local_end.date(), time.min, tzinfo=tz)
    while day <= last_day:
        weekday_key = WEEKDAY_KEYS[day.weekday()]

        for window in _windows_for_day(profile.business_hours, weekday_key):
            slots = _generate_slots_in_window(
                day,
                window,
                duration,
                busy_blocks,
                "business",
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
                    busy_blocks,
                    "extended",
                    range_start,
                    range_end,
                )
                free_slots.extend(slots)

        day += timedelta(days=1)

    free_slots.sort(key=lambda slot: slot.start)
    return AvailabilityResult(free_slots=free_slots, business_slot_count=business_count)
