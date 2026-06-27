"""Read-side queries for the daily overview and board index counts.

Kept separate from views so the same bucketing logic backs the board home, the
per-board pending counts on the index, and (later) the cross-board overview.
"""

import calendar
import datetime
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from .models import Post
from .scheduling import local_date

# Sunday-first weekday headers for the schedule grid.
WEEKDAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
_SUNDAY_FIRST = 6

# Statuses that take a post out of the active pipeline.
INACTIVE_STATUSES = [
    Post.Status.PUBLISHED,
    Post.Status.ARCHIVED,
    Post.Status.CANCELLED,
]
STALLED_DAYS = 3
RECENT_DAYS = 7
WEEK_DAYS = 7


def board_posts(board):
    """All posts in a board, with campaign + board + assets preloaded."""
    return (
        Post.objects.filter(campaign__board=board)
        .select_related("campaign__board")
        .prefetch_related("assets")
    )


def daily_sections(board, *, now=None):
    """The board home sections as a dict of post lists, in display order.

    Buckets are non-overlapping by ``scheduled_at`` relative to the board's
    local "today". ``now`` is injectable for deterministic tests.
    """
    now = now or timezone.now()
    tz = ZoneInfo(board.timezone)
    start_today = datetime.datetime.combine(
        now.astimezone(tz).date(), datetime.time.min, tzinfo=tz
    )
    end_today = start_today + datetime.timedelta(days=1)
    end_week = end_today + datetime.timedelta(days=WEEK_DAYS)

    posts = board_posts(board)
    active = posts.exclude(status__in=INACTIVE_STATUSES)
    stalled_before = now - datetime.timedelta(days=STALLED_DAYS)
    recent_after = now - datetime.timedelta(days=RECENT_DAYS)

    return {
        "overdue": list(active.filter(scheduled_at__lt=start_today)),
        "today": list(
            active.filter(scheduled_at__gte=start_today, scheduled_at__lt=end_today)
        ),
        "this_week": list(
            active.filter(scheduled_at__gte=end_today, scheduled_at__lt=end_week)
        ),
        "awaiting": list(
            posts.filter(status=Post.Status.DRAFTING).filter(
                Q(scheduled_at__isnull=True) | Q(modified_date__lt=stalled_before)
            )
        ),
        "recently_published": list(
            posts.filter(status=Post.Status.PUBLISHED, modified_date__gte=recent_after)
        ),
    }


def pending_summary(board, *, now=None):
    """At-a-glance counts for a board index row: pending and overdue."""
    sections = daily_sections(board, now=now)
    return {
        "overdue": len(sections["overdue"]),
        "pending": len(sections["today"]) + len(sections["this_week"]),
    }


def month_schedule(board, year, month):
    """A month calendar grid of posts placed on their board-local dates.

    Returns weeks of day cells (including leading/trailing days from adjacent
    months, flagged ``in_month=False``) plus the previous/next month for
    navigation. Raises ``ValueError`` for an out-of-range year or month, which
    the view catches to fall back to the current month.
    """
    tz = ZoneInfo(board.timezone)
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    start_dt = datetime.datetime.combine(first, datetime.time.min, tzinfo=tz)
    end_dt = datetime.datetime.combine(last, datetime.time.max, tzinfo=tz)

    by_day = {}
    for post in board_posts(board).filter(
        scheduled_at__gte=start_dt, scheduled_at__lte=end_dt
    ):
        day = local_date(post.scheduled_at, board.timezone)
        by_day.setdefault(day, []).append(post)

    cal = calendar.Calendar(firstweekday=_SUNDAY_FIRST)
    weeks = [
        [
            {"date": day, "in_month": day.month == month, "posts": by_day.get(day, [])}
            for day in week
        ]
        for week in cal.monthdatescalendar(year, month)
    ]

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": weeks,
        "headers": WEEKDAY_HEADERS,
        "label": first.strftime("%B %Y"),
        "prev": {"year": prev_year, "month": prev_month},
        "next": {"year": next_year, "month": next_month},
    }


def campaign_stats(campaign, *, now=None):
    """At-a-glance dashboard numbers for a single campaign.

    ``now`` is injectable for deterministic tests (used for "days until event").
    """
    posts = list(campaign.posts.prefetch_related("assets"))
    inactive = set(INACTIVE_STATUSES)
    published = sum(1 for post in posts if post.status == Post.Status.PUBLISHED)
    planned = sum(1 for post in posts if post.status not in inactive)
    overdue = sum(1 for post in posts if post.is_overdue)
    expected_assets = sum(len(post.expected_asset_list) for post in posts)
    delivered_assets = sum(post.attached_asset_count for post in posts)
    posts_missing_assets = sum(1 for post in posts if post.is_missing_asset)

    days_until_event = None
    if campaign.event_date is not None:
        now = now or timezone.now()
        today = local_date(now, campaign.board.timezone)
        days_until_event = (campaign.event_date - today).days

    return {
        "total_posts": len(posts),
        "published": published,
        "planned": planned,
        "overdue": overdue,
        "expected_assets": expected_assets,
        "delivered_assets": delivered_assets,
        "posts_missing_assets": posts_missing_assets,
        "event_date": campaign.event_date,
        "days_until_event": days_until_event,
    }
