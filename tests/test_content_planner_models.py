"""Model, scheduling, and slug behavior for content_planner."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError

from content_planner.models import (
    Asset,
    Campaign,
    ContentBoard,
    ContentCollaborator,
    ContentInvitation,
    Post,
    Tag,
)
from content_planner.scheduling import (
    compute_scheduled_at,
    local_date,
    local_time_of_day,
)
from content_planner.slugs import generate_unique_slug
from core.models import mint_invitation_key

User = get_user_model()

VANCOUVER = "America/Vancouver"


@pytest.fixture
def board(db):
    owner = User.objects.create_user(username="boardowner")
    return ContentBoard.objects.create(
        name="Mariatta personal", slug="mariatta", owner=owner, timezone=VANCOUVER
    )


# ---------------------------------------------------------------- __str__


def test_board_str(board):
    assert str(board) == "Mariatta personal"


def test_collaborator_str(board):
    user = User.objects.create_user(username="collab")
    collab = ContentCollaborator.objects.create(board=board, user=user)
    assert str(collab) == f"{user} on {board}"


def test_invitation_str(board):
    invite = ContentInvitation.objects.create(
        board=board,
        email="friend@example.com",
        inviter=board.owner,
        key=mint_invitation_key(),
    )
    assert str(invite) == "Invite friend@example.com to Mariatta personal"


def test_tag_str(board):
    tag = Tag.objects.create(board=board, name="advocacy")
    assert str(tag) == "advocacy"


def test_campaign_str(board):
    campaign = Campaign.objects.create(board=board, name="Blog series")
    assert str(campaign) == "Blog series"


def test_asset_str(board):
    asset = Asset.objects.create(board=board, name="Hero image")
    assert str(asset) == "Hero image"


def test_post_str(board):
    campaign = Campaign.objects.create(board=board, name="Blog series")
    post = Post.objects.create(campaign=campaign, title="Part 1", channel="blog")
    assert str(post) == "Part 1"


# ---------------------------------------------------------------- tags


def test_tag_save_strips_whitespace(board):
    tag = Tag.objects.create(board=board, name="  PyCon  ")
    assert tag.name == "PyCon"


def test_tag_unique_case_insensitive_per_board(board):
    Tag.objects.create(board=board, name="PyCon")
    with pytest.raises(IntegrityError):
        Tag.objects.create(board=board, name="pycon")


def test_tag_same_name_coexists_across_boards(board):
    other = ContentBoard.objects.create(
        name="PyLadiesCon", slug="pyladiescon", owner=board.owner
    )
    a = Tag.objects.create(board=board, name="PyCon")
    b = Tag.objects.create(board=other, name="PyCon")
    assert a.pk != b.pk


# ---------------------------------------------------------------- slugs


def test_campaign_slug_generated_from_name(board):
    campaign = Campaign.objects.create(board=board, name="Confession Series!")
    assert campaign.slug == "confession-series"


def test_campaign_slug_collision_suffixed(board):
    first = Campaign.objects.create(board=board, name="Same Name")
    second = Campaign.objects.create(board=board, name="Same Name")
    assert first.slug == "same-name"
    assert second.slug == "same-name-2"


def test_campaign_slug_unchanged_when_name_unchanged(board):
    campaign = Campaign.objects.create(board=board, name="Stable")
    campaign.slug = "manually-pinned"
    campaign.name = "Stable"  # unchanged
    campaign.save()
    assert campaign.slug == "manually-pinned"


def test_campaign_slug_regenerates_on_rename(board):
    campaign = Campaign.objects.create(board=board, name="First Title")
    campaign.name = "Second Title"
    campaign.save()
    assert campaign.slug == "second-title"


def test_post_slug_generated_and_collision_per_campaign(board):
    campaign = Campaign.objects.create(board=board, name="C")
    a = Post.objects.create(campaign=campaign, title="Announce", channel="blog")
    b = Post.objects.create(campaign=campaign, title="Announce", channel="mastodon")
    assert a.slug == "announce"
    assert b.slug == "announce-2"


def test_post_slug_unchanged_when_title_unchanged(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="Keep", channel="blog")
    post.slug = "pinned"
    post.title = "Keep"
    post.save()
    assert post.slug == "pinned"


def test_post_slug_regenerates_on_retitle(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="First Title", channel="blog")
    post.title = "Second Title"
    post.save()
    assert post.slug == "second-title"


def test_generate_unique_slug_word_boundary_truncation(board):
    slug = generate_unique_slug(
        value="alpha beta gamma delta",
        max_length=12,
        queryset=Campaign.objects.none(),
    )
    # "alpha-beta-gamma"[:12] -> "alpha-beta-g" -> trimmed at last "-" -> "alpha-beta"
    assert slug == "alpha-beta"


def test_generate_unique_slug_single_long_word(board):
    slug = generate_unique_slug(
        value="x" * 30, max_length=10, queryset=Campaign.objects.none()
    )
    assert slug == "x" * 10


def test_generate_unique_slug_empty_falls_back(board):
    slug = generate_unique_slug(
        value="!!!", max_length=20, queryset=Campaign.objects.none()
    )
    assert slug == "item"


# ---------------------------------------------------------------- anchoring


def test_non_anchored_campaign_leaves_post_untouched(board):
    campaign = Campaign.objects.create(board=board, name="No event")
    when = datetime.datetime(2026, 5, 30, 9, 0, tzinfo=ZoneInfo(VANCOUVER))
    post = Post.objects.create(
        campaign=campaign, title="P", channel="blog", scheduled_at=when
    )
    assert post.anchor_offset_days is None
    assert post.scheduled_at == when


def test_offset_with_no_time_defaults_to_0900(board):
    campaign = Campaign.objects.create(
        board=board, name="Event", event_date=datetime.date(2026, 5, 15)
    )
    post = Post.objects.create(
        campaign=campaign,
        title="Save the date",
        channel="newsletter",
        anchor_offset_days=-90,
    )
    local = post.scheduled_at.astimezone(ZoneInfo(VANCOUVER))
    assert local.date() == datetime.date(2026, 2, 14)
    assert local.time() == datetime.time(9, 0)


def test_offset_preserves_existing_time_of_day(board):
    campaign = Campaign.objects.create(
        board=board, name="Event", event_date=datetime.date(2026, 5, 15)
    )
    seed = datetime.datetime(2026, 1, 1, 14, 30, tzinfo=ZoneInfo(VANCOUVER))
    post = Post.objects.create(
        campaign=campaign,
        title="Reminder",
        channel="newsletter",
        anchor_offset_days=-14,
        scheduled_at=seed,
    )
    local = post.scheduled_at.astimezone(ZoneInfo(VANCOUVER))
    assert local.date() == datetime.date(2026, 5, 1)
    assert local.time() == datetime.time(14, 30)


def test_scheduled_at_derives_offset_when_offset_missing(board):
    campaign = Campaign.objects.create(
        board=board, name="Event", event_date=datetime.date(2026, 5, 15)
    )
    when = datetime.datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo(VANCOUVER))
    post = Post.objects.create(
        campaign=campaign, title="X", channel="blog", scheduled_at=when
    )
    assert post.anchor_offset_days == -5


def test_anchored_campaign_with_no_dates_stays_null(board):
    campaign = Campaign.objects.create(
        board=board, name="Event", event_date=datetime.date(2026, 5, 15)
    )
    post = Post.objects.create(campaign=campaign, title="TBD", channel="blog")
    assert post.scheduled_at is None
    assert post.anchor_offset_days is None


def test_changing_event_date_recomputes_unlocked_skips_locked(board):
    campaign = Campaign.objects.create(
        board=board, name="Event", event_date=datetime.date(2026, 5, 15)
    )
    movable = Post.objects.create(
        campaign=campaign,
        title="Movable",
        channel="newsletter",
        anchor_offset_days=-10,
    )
    locked = Post.objects.create(
        campaign=campaign,
        title="Locked",
        channel="newsletter",
        anchor_offset_days=-10,
        date_locked=True,
    )
    locked_before = locked.scheduled_at

    campaign.event_date = datetime.date(2026, 6, 15)
    campaign.save()

    movable.refresh_from_db()
    locked.refresh_from_db()
    assert movable.scheduled_at.astimezone(ZoneInfo(VANCOUVER)).date() == datetime.date(
        2026, 6, 5
    )
    assert locked.scheduled_at == locked_before


# ---------------------------------------------------------------- scheduling unit


def test_assign_slug_basic(board):
    new = ContentBoard(name="My New Board", owner=board.owner)
    new.assign_slug()
    assert new.slug == "my-new-board"


def test_assign_slug_avoids_reserved(board):
    new = ContentBoard(name="All", owner=board.owner)
    new.assign_slug()
    assert new.slug == "all-2"


def test_assign_slug_on_saved_board_excludes_self(board):
    board.name = "Renamed Board"
    board.assign_slug()
    assert board.slug == "renamed-board"


def test_assign_slug_collision(board):
    other = ContentBoard.objects.create(name="Shared", slug="shared", owner=board.owner)
    new = ContentBoard(name="Shared", owner=board.owner)
    new.assign_slug()
    assert new.slug == "shared-2"
    assert other.slug == "shared"


# ---------------------------------------------------------------- scheduling unit


def test_is_overdue_true_for_past_active_post(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(
        campaign=campaign,
        title="Late",
        channel="blog",
        status="ready",
        scheduled_at=datetime.datetime(2020, 1, 1, 9, 0, tzinfo=ZoneInfo(VANCOUVER)),
    )
    assert post.is_overdue is True


def test_is_overdue_false_when_unscheduled(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="TBD", channel="blog")
    assert post.is_overdue is False


def test_is_overdue_false_for_terminal_status(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(
        campaign=campaign,
        title="Done",
        channel="blog",
        status="published",
        scheduled_at=datetime.datetime(2020, 1, 1, 9, 0, tzinfo=ZoneInfo(VANCOUVER)),
    )
    assert post.is_overdue is False


def test_is_overdue_false_for_future_post(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(
        campaign=campaign,
        title="Soon",
        channel="blog",
        status="ready",
        scheduled_at=datetime.datetime(2999, 1, 1, 9, 0, tzinfo=ZoneInfo(VANCOUVER)),
    )
    assert post.is_overdue is False


def test_compute_scheduled_at_default_time():
    result = compute_scheduled_at(
        event_date=datetime.date(2026, 5, 15),
        offset_days=0,
        time_of_day=None,
        tz_name=VANCOUVER,
    )
    assert result == datetime.datetime(2026, 5, 15, 9, 0, tzinfo=ZoneInfo(VANCOUVER))


def test_compute_scheduled_at_explicit_time():
    result = compute_scheduled_at(
        event_date=datetime.date(2026, 5, 15),
        offset_days=2,
        time_of_day=datetime.time(18, 0),
        tz_name=VANCOUVER,
    )
    assert result == datetime.datetime(2026, 5, 17, 18, 0, tzinfo=ZoneInfo(VANCOUVER))


def test_local_time_of_day_and_date():
    utc = datetime.datetime(2026, 5, 15, 2, 30, tzinfo=ZoneInfo("UTC"))
    # 02:30 UTC is 19:30 the previous day in Vancouver (PDT, -7).
    assert local_time_of_day(utc, VANCOUVER) == datetime.time(19, 30)
    assert local_date(utc, VANCOUVER) == datetime.date(2026, 5, 14)
