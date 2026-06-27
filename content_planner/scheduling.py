"""Timezone and event-anchor math for content_planner.

Single source of truth for "when does this go out" is ``Post.scheduled_at``
(an aware ``DateTimeField`` stored in UTC). For event-anchored campaigns the
value is derived from ``Campaign.event_date`` plus a per-post day offset and a
time-of-day, all interpreted in the board's timezone. These helpers do the
conversions so the models never hand-roll timezone arithmetic.
"""

import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIME_OF_DAY = datetime.time(9, 0)


def compute_scheduled_at(*, event_date, offset_days, time_of_day, tz_name):
    """Aware datetime for ``event_date + offset_days`` at ``time_of_day``.

    ``time_of_day`` of ``None`` falls back to 09:00 in the board's tz. The
    returned value carries the board's zone; Django stores it as UTC.
    """
    target_date = event_date + datetime.timedelta(days=offset_days)
    naive = datetime.datetime.combine(target_date, time_of_day or DEFAULT_TIME_OF_DAY)
    return naive.replace(tzinfo=ZoneInfo(tz_name))


def local_time_of_day(dt_aware, tz_name):
    """Time-of-day component of ``dt_aware`` as seen in the board's tz."""
    return dt_aware.astimezone(ZoneInfo(tz_name)).time()


def local_date(dt_aware, tz_name):
    """Calendar date of ``dt_aware`` as seen in the board's tz."""
    return dt_aware.astimezone(ZoneInfo(tz_name)).date()
