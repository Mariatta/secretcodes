"""Daily-overview selectors and tag resolution."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from content_planner.models import Campaign, ContentBoard, Post, Tag
from content_planner.selectors import (
    WEEKDAY_HEADERS,
    daily_sections,
    month_schedule,
    pending_summary,
)
from content_planner.tagging import parse_tag_names, resolve_tags

User = get_user_model()

VANCOUVER = "America/Vancouver"
NOW = datetime.datetime(2026, 6, 15, 18, 0, tzinfo=ZoneInfo("UTC"))


@pytest.fixture
def board(db):
    owner = User.objects.create_user(username="owner")
    return ContentBoard.objects.create(
        name="Board", slug="board", owner=owner, timezone=VANCOUVER
    )


@pytest.fixture
def campaign(board):
    return Campaign.objects.create(board=board, name="C")


def _at(y, m, d, hh=9):
    return datetime.datetime(y, m, d, hh, 0, tzinfo=ZoneInfo(VANCOUVER))


def test_daily_sections_buckets(board, campaign):
    overdue = Post.objects.create(
        campaign=campaign,
        title="Overdue",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 10),
    )
    today = Post.objects.create(
        campaign=campaign,
        title="Today",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 15, 12),
    )
    week = Post.objects.create(
        campaign=campaign,
        title="Week",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 18),
    )
    awaiting_null = Post.objects.create(
        campaign=campaign,
        title="NoDate",
        channel="blog",
        status="drafting",
    )
    stalled = Post.objects.create(
        campaign=campaign,
        title="Stalled",
        channel="blog",
        status="drafting",
        scheduled_at=_at(2026, 7, 1),
    )
    Post.objects.filter(pk=stalled.pk).update(
        modified_date=NOW - datetime.timedelta(days=10)
    )
    published = Post.objects.create(
        campaign=campaign,
        title="Done",
        channel="blog",
        status="published",
    )
    Post.objects.filter(pk=published.pk).update(
        modified_date=NOW - datetime.timedelta(days=3)
    )

    sections = daily_sections(board, now=NOW)
    assert [p.title for p in sections["overdue"]] == ["Overdue"]
    assert [p.title for p in sections["today"]] == ["Today"]
    assert [p.title for p in sections["this_week"]] == ["Week"]
    titles_awaiting = {p.title for p in sections["awaiting"]}
    assert titles_awaiting == {"NoDate", "Stalled"}
    assert [p.title for p in sections["recently_published"]] == ["Done"]
    # sanity: ids resolve to the rows we made
    assert overdue.pk and today.pk and week.pk and awaiting_null.pk


def test_pending_summary_counts(board, campaign):
    Post.objects.create(
        campaign=campaign,
        title="Overdue",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 10),
    )
    Post.objects.create(
        campaign=campaign,
        title="Today",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 15, 12),
    )
    Post.objects.create(
        campaign=campaign,
        title="Week",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 18),
    )
    summary = pending_summary(board, now=NOW)
    assert summary == {"overdue": 1, "pending": 2}


def test_daily_sections_defaults_now(board):
    # Exercise the now-defaulting branch (no fixed clock passed).
    assert daily_sections(board) == {
        "overdue": [],
        "today": [],
        "this_week": [],
        "awaiting": [],
        "recently_published": [],
    }


# ------------------------------------------------------------ month grid


def _cells_by_date(grid):
    return {cell["date"]: cell for week in grid["weeks"] for cell in week}


def test_month_schedule_places_post_on_its_day(board, campaign):
    post = Post.objects.create(
        campaign=campaign,
        title="Mid",
        channel="blog",
        status="ready",
        scheduled_at=_at(2026, 6, 15, 12),
    )
    grid = month_schedule(board, 2026, 6)
    assert grid["label"] == "June 2026"
    assert grid["headers"] == WEEKDAY_HEADERS
    assert grid["prev"] == {"year": 2026, "month": 5}
    assert grid["next"] == {"year": 2026, "month": 7}
    cell = _cells_by_date(grid)[datetime.date(2026, 6, 15)]
    assert cell["in_month"] is True
    assert post in cell["posts"]


def test_month_schedule_out_of_month_cells_flagged(board):
    grid = month_schedule(board, 2026, 6)
    # June 2026 starts on a Monday, so a Sunday-first grid leads with May 31.
    may_cell = _cells_by_date(grid)[datetime.date(2026, 5, 31)]
    assert may_cell["in_month"] is False
    assert may_cell["posts"] == []


def test_month_schedule_january_wraps_to_prev_december(board):
    grid = month_schedule(board, 2026, 1)
    assert grid["prev"] == {"year": 2025, "month": 12}


def test_month_schedule_december_wraps_to_next_january(board):
    grid = month_schedule(board, 2026, 12)
    assert grid["next"] == {"year": 2027, "month": 1}


# ------------------------------------------------------------ tagging


def test_parse_tag_names_dedup_and_strip():
    assert parse_tag_names("PyCon, pycon , ,Advocacy") == ["PyCon", "Advocacy"]


def test_resolve_tags_reuses_and_creates(board):
    existing = Tag.objects.create(board=board, name="PyCon")
    result = resolve_tags(board, ["pycon", "New One"])
    assert result[0].pk == existing.pk  # matched case-insensitively
    assert result[1].name == "New One"
    assert Tag.objects.filter(board=board, name="New One").exists()
