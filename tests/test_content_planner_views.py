"""Web UI: views, forms, and the board_required decorator."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from content_planner.forms import PostCreateForm, PostForm
from content_planner.models import Asset, Campaign, ContentBoard, Post

User = get_user_model()


@pytest.fixture
def access_perm(db):
    return Permission.objects.get(
        codename="access_content_planner",
        content_type__app_label="content_planner",
    )


@pytest.fixture
def user(db, access_perm):
    u = User.objects.create_user(username="owner", password="pw")
    u.user_permissions.add(access_perm)
    return u


@pytest.fixture
def board(user):
    return ContentBoard.objects.create(
        name="Mariatta personal", slug="mariatta", owner=user
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


# ------------------------------------------------------------------ index


def test_index_landing_for_non_user(client):
    resp = client.get(reverse("content_planner:index"))
    assert resp.status_code == 200
    assert b"invite-only" in resp.content


def test_index_single_board_redirects(auth_client, board):
    resp = auth_client.get(reverse("content_planner:index"))
    assert resp.status_code == 302
    assert resp.url == reverse(
        "content_planner:board_home", kwargs={"board_slug": board.slug}
    )


def test_index_lists_multiple_boards(auth_client, user, board):
    ContentBoard.objects.create(name="PyLadiesCon", slug="plc", owner=user)
    resp = auth_client.get(reverse("content_planner:index"))
    assert resp.status_code == 200
    assert b"Mariatta personal" in resp.content
    assert b"PyLadiesCon" in resp.content


def test_index_empty_state(auth_client):
    resp = auth_client.get(reverse("content_planner:index"))
    assert resp.status_code == 200
    assert b"any boards yet" in resp.content


# ------------------------------------------------------------ board_required


def test_board_home_requires_app_permission(client, board):
    plain = User.objects.create_user(username="plain", password="pw")
    client.force_login(plain)
    resp = client.get(
        reverse("content_planner:board_home", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 302  # redirected to login by user_passes_test


def test_board_home_404_for_non_member(client, access_perm, board):
    stranger = User.objects.create_user(username="stranger", password="pw")
    stranger.user_permissions.add(access_perm)
    client.force_login(stranger)
    resp = client.get(
        reverse("content_planner:board_home", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 404


def test_board_home_renders_for_owner(auth_client, board):
    resp = auth_client.get(
        reverse("content_planner:board_home", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 200
    assert b"Today" in resp.content


def test_board_home_empty_state_offers_import(auth_client, board):
    """With no campaigns, the overview still links to JSON import — importing
    is a way to create your first campaign."""
    resp = auth_client.get(
        reverse("content_planner:board_home", kwargs={"board_slug": board.slug})
    )
    import_url = reverse(
        "content_planner:campaign_create_from_chat",
        kwargs={"board_slug": board.slug},
    )
    assert import_url.encode() in resp.content


def test_no_external_script_or_style_resources(auth_client, board):
    """Guard: all JS/CSS is served locally — no CDNs (and thus no third-party
    cookies). Fails if a template ever adds an external script/stylesheet."""
    import re

    html = auth_client.get(
        reverse("content_planner:board_home", kwargs={"board_slug": board.slug})
    ).content.decode()
    urls = re.findall(r'<script[^>]+src="([^"]+)"', html)
    urls += re.findall(r'<link[^>]+href="([^"]+)"', html)
    assert urls  # sanity: there are scripts/styles to check
    external = [u for u in urls if u.startswith(("http://", "https://", "//"))]
    assert external == [], f"external resources found: {external}"


# ------------------------------------------------------------ board_create


def test_board_create_get(auth_client):
    resp = auth_client.get(reverse("content_planner:board_create"))
    assert resp.status_code == 200


def test_board_create_post_assigns_slug(auth_client, user):
    resp = auth_client.post(
        reverse("content_planner:board_create"),
        {"name": "New Board", "timezone": "America/Vancouver", "description": ""},
    )
    board = ContentBoard.objects.get(name="New Board")
    assert board.owner == user
    assert board.slug == "new-board"
    assert resp.status_code == 302


def test_board_create_post_invalid(auth_client):
    resp = auth_client.post(reverse("content_planner:board_create"), {"name": ""})
    assert resp.status_code == 200
    assert not ContentBoard.objects.filter(name="").exists()


# ------------------------------------------------------------ schedule


def test_schedule_default_month(auth_client, board):
    resp = auth_client.get(
        reverse("content_planner:schedule", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 200
    assert b"Schedule" in resp.content


def test_schedule_specific_month_shows_posts(auth_client, board):
    import datetime
    from zoneinfo import ZoneInfo

    campaign = Campaign.objects.create(board=board, name="C")
    Post.objects.create(
        campaign=campaign,
        title="GridPost",
        channel="blog",
        status="ready",
        scheduled_at=datetime.datetime(
            2026, 6, 15, 9, 0, tzinfo=ZoneInfo("America/Vancouver")
        ),
    )
    resp = auth_client.get(
        reverse("content_planner:schedule", kwargs={"board_slug": board.slug}),
        {"year": "2026", "month": "6"},
    )
    assert resp.status_code == 200
    assert b"June 2026" in resp.content
    assert b"GridPost" in resp.content


def test_schedule_invalid_params_fall_back(auth_client, board):
    resp = auth_client.get(
        reverse("content_planner:schedule", kwargs={"board_slug": board.slug}),
        {"year": "abc", "month": "6"},
    )
    assert resp.status_code == 200


def test_schedule_out_of_range_month_falls_back(auth_client, board):
    resp = auth_client.get(
        reverse("content_planner:schedule", kwargs={"board_slug": board.slug}),
        {"year": "2026", "month": "13"},
    )
    assert resp.status_code == 200


# ------------------------------------------------------------ campaigns


def test_campaign_list(auth_client, board):
    Campaign.objects.create(board=board, name="Series A")
    resp = auth_client.get(
        reverse("content_planner:campaign_list", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 200
    assert b"Series A" in resp.content


def test_campaign_create_get(auth_client, board):
    resp = auth_client.get(
        reverse("content_planner:campaign_create", kwargs={"board_slug": board.slug})
    )
    assert resp.status_code == 200


def test_campaign_create_post_resolves_tags(auth_client, board):
    resp = auth_client.post(
        reverse("content_planner:campaign_create", kwargs={"board_slug": board.slug}),
        {
            "name": "Launch",
            "tags": "advocacy, PyCon",
            "narrative_notes": "",
            "source_url": "",
        },
    )
    assert resp.status_code == 302
    campaign = Campaign.objects.get(name="Launch")
    assert set(campaign.tags.values_list("name", flat=True)) == {"advocacy", "PyCon"}


def test_campaign_create_post_invalid(auth_client, board):
    resp = auth_client.post(
        reverse("content_planner:campaign_create", kwargs={"board_slug": board.slug}),
        {"name": ""},
    )
    assert resp.status_code == 200


def test_campaign_edit_get_prefills_tags(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Editable")
    campaign.tags.set([campaign.board.tags.create(name="existing")])
    resp = auth_client.get(
        reverse(
            "content_planner:campaign_edit",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        )
    )
    assert resp.status_code == 200
    assert b"existing" in resp.content


def test_campaign_edit_post(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Old Name")
    resp = auth_client.post(
        reverse(
            "content_planner:campaign_edit",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {"name": "New Name", "tags": "", "narrative_notes": "", "source_url": ""},
    )
    assert resp.status_code == 302
    campaign.refresh_from_db()
    assert campaign.name == "New Name"


def test_campaign_edit_post_invalid(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Keep")
    resp = auth_client.post(
        reverse(
            "content_planner:campaign_edit",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {"name": ""},
    )
    assert resp.status_code == 200


def test_campaign_detail(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Detail Me")
    resp = auth_client.get(
        reverse(
            "content_planner:campaign_detail",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        )
    )
    assert resp.status_code == 200
    assert b"Detail Me" in resp.content


def test_campaign_detail_includes_stats(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Stats Me")
    Post.objects.create(campaign=campaign, title="P", channel="blog")
    resp = auth_client.get(
        reverse(
            "content_planner:campaign_detail",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        )
    )
    assert resp.context["stats"]["total_posts"] == 1


# ------------------------------------------------------------ posts


@pytest.fixture
def campaign(board):
    return Campaign.objects.create(board=board, name="Campaign")


def test_post_create_get(auth_client, board, campaign):
    resp = auth_client.get(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        )
    )
    assert resp.status_code == 200


def test_post_create_single_channel_sets_created_by(auth_client, user, board, campaign):
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {
            "title": "Announce",
            "channels": ["blog"],
            "status": "drafting",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    post = Post.objects.get(title="Announce")
    assert post.created_by == user
    assert post.channel == "blog"


def test_post_create_fans_out_to_multiple_channels(auth_client, user, board, campaign):
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {
            "title": "Cross-post",
            "channels": ["blog", "mastodon", "linkedin"],
            "status": "drafting",
            "body_snippet": "shared body",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302  # redirects to the campaign detail
    posts = Post.objects.filter(title="Cross-post")
    assert posts.count() == 3
    assert set(posts.values_list("channel", flat=True)) == {
        "blog",
        "mastodon",
        "linkedin",
    }
    assert all(p.created_by == user for p in posts)
    assert all(p.body_snippet == "shared body" for p in posts)


def test_post_create_records_expected_asset(auth_client, board, campaign):
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {
            "title": "Hero post",
            "channels": ["blog"],
            "status": "drafting",
            "expected_asset": "hero image",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    post = Post.objects.get(title="Hero post")
    assert post.expected_asset == "hero image"
    assert post.is_missing_asset is True


def test_post_create_requires_a_channel(auth_client, board, campaign):
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {"title": "No channel", "status": "drafting"},
    )
    assert resp.status_code == 200
    assert not Post.objects.filter(title="No channel").exists()


def test_post_edit(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="Before", channel="blog")
    resp = auth_client.post(
        reverse(
            "content_planner:post_edit",
            kwargs={
                "board_slug": board.slug,
                "slug": campaign.slug,
                "post_slug": post.slug,
            },
        ),
        {
            "title": "After",
            "channel": "blog",
            "status": "ready",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.title == "After"
    assert post.status == "ready"


def test_post_edit_get(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="EditGet", channel="blog")
    resp = auth_client.get(
        reverse(
            "content_planner:post_edit",
            kwargs={
                "board_slug": board.slug,
                "slug": campaign.slug,
                "post_slug": post.slug,
            },
        )
    )
    assert resp.status_code == 200


def _bulk_url(board, campaign):
    return reverse(
        "content_planner:campaign_bulk_update",
        kwargs={"board_slug": board.slug, "slug": campaign.slug},
    )


def test_bulk_set_status_updates_selected(auth_client, board, campaign):
    p1 = Post.objects.create(campaign=campaign, title="A", channel="blog")
    p2 = Post.objects.create(campaign=campaign, title="B", channel="blog")
    resp = auth_client.post(
        _bulk_url(board, campaign),
        {"posts": [p1.pk, p2.pk], "action": "set_status", "status": "published"},
    )
    assert resp.status_code == 302
    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.status == "published"
    assert p2.status == "published"


def test_bulk_no_selection_changes_nothing(auth_client, board, campaign):
    post = Post.objects.create(
        campaign=campaign, title="A", channel="blog", status="drafting"
    )
    resp = auth_client.post(
        _bulk_url(board, campaign), {"action": "set_status", "status": "published"}
    )
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.status == "drafting"


def test_bulk_invalid_status_rejected(auth_client, board, campaign):
    post = Post.objects.create(
        campaign=campaign, title="A", channel="blog", status="drafting"
    )
    resp = auth_client.post(
        _bulk_url(board, campaign),
        {"posts": [post.pk], "action": "set_status", "status": "bogus"},
    )
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.status == "drafting"


def test_bulk_unknown_action_rejected(auth_client, board, campaign):
    post = Post.objects.create(
        campaign=campaign, title="A", channel="blog", status="drafting"
    )
    resp = auth_client.post(
        _bulk_url(board, campaign), {"posts": [post.pk], "action": "frobnicate"}
    )
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.status == "drafting"


def test_bulk_mark_done_wins_over_action_dropdown(auth_client, board, campaign):
    p1 = Post.objects.create(campaign=campaign, title="A", channel="blog")
    p2 = Post.objects.create(campaign=campaign, title="B", channel="blog")
    resp = auth_client.post(
        _bulk_url(board, campaign),
        {
            "posts": [p1.pk, p2.pk],
            "quick_action": "mark_done",
            "action": "set_status",
            "status": "drafting",
        },
    )
    assert resp.status_code == 302
    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.status == "published"
    assert p2.status == "published"


def _mark_done_url(board, campaign, post):
    return reverse(
        "content_planner:post_mark_done",
        kwargs={
            "board_slug": board.slug,
            "slug": campaign.slug,
            "post_slug": post.slug,
        },
    )


def test_post_mark_done(auth_client, board, campaign):
    post = Post.objects.create(
        campaign=campaign, title="A", channel="blog", status="drafting"
    )
    resp = auth_client.post(_mark_done_url(board, campaign, post))
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "content_planner:campaign_detail",
        kwargs={"board_slug": board.slug, "slug": campaign.slug},
    )
    post.refresh_from_db()
    assert post.status == "published"


def test_post_mark_done_returns_to_next(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="A", channel="blog")
    board_home = reverse(
        "content_planner:board_home", kwargs={"board_slug": board.slug}
    )
    resp = auth_client.post(
        _mark_done_url(board, campaign, post), {"next": board_home}
    )
    assert resp.status_code == 302
    assert resp["Location"] == board_home


def test_post_mark_done_rejects_offsite_next(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="A", channel="blog")
    resp = auth_client.post(
        _mark_done_url(board, campaign, post), {"next": "https://evil.example/"}
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "content_planner:campaign_detail",
        kwargs={"board_slug": board.slug, "slug": campaign.slug},
    )


def test_post_delete(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="Doomed", channel="blog")
    resp = auth_client.post(
        reverse(
            "content_planner:post_delete",
            kwargs={
                "board_slug": board.slug,
                "slug": campaign.slug,
                "post_slug": post.slug,
            },
        )
    )
    assert resp.status_code == 302
    assert not Post.objects.filter(pk=post.pk).exists()


def test_post_create_records_hashtags(auth_client, board, campaign):
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": campaign.slug},
        ),
        {
            "title": "Tagged",
            "channels": ["mastodon"],
            "status": "drafting",
            "hashtags": "#python",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
            "expected_asset": "",
        },
    )
    assert resp.status_code == 302
    assert Post.objects.get(title="Tagged").hashtags == "#python"


def test_post_detail(auth_client, board, campaign):
    post = Post.objects.create(campaign=campaign, title="Show Me", channel="blog")
    resp = auth_client.get(
        reverse(
            "content_planner:post_detail",
            kwargs={
                "board_slug": board.slug,
                "slug": campaign.slug,
                "post_slug": post.slug,
            },
        )
    )
    assert resp.status_code == 200
    assert b"Show Me" in resp.content


def test_post_detail_prev_next(auth_client, board, campaign):
    import datetime
    from zoneinfo import ZoneInfo

    def _detail_url(post):
        return reverse(
            "content_planner:post_detail",
            kwargs={
                "board_slug": board.slug,
                "slug": campaign.slug,
                "post_slug": post.slug,
            },
        )

    utc = ZoneInfo("UTC")
    p1 = Post.objects.create(
        campaign=campaign,
        title="One",
        channel="blog",
        scheduled_at=datetime.datetime(2026, 1, 1, tzinfo=utc),
    )
    p2 = Post.objects.create(
        campaign=campaign,
        title="Two",
        channel="blog",
        scheduled_at=datetime.datetime(2026, 1, 2, tzinfo=utc),
    )
    p3 = Post.objects.create(
        campaign=campaign,
        title="Three",
        channel="blog",
        scheduled_at=datetime.datetime(2026, 1, 3, tzinfo=utc),
    )

    middle = auth_client.get(_detail_url(p2))
    assert middle.context["prev_post"] == p1
    assert middle.context["next_post"] == p3

    first = auth_client.get(_detail_url(p1))
    assert first.context["prev_post"] is None
    assert first.context["next_post"] == p2

    last = auth_client.get(_detail_url(p3))
    assert last.context["prev_post"] == p2
    assert last.context["next_post"] is None


# ------------------------------------------------------------ PostForm scoping


def test_post_form_asset_field_present_but_empty(board, campaign):
    form = PostForm(campaign=campaign)
    assert "assets" in form.fields
    assert not form.fields["assets"].queryset.exists()


def test_post_form_rejects_cross_board_asset(board, campaign):
    Asset.objects.create(board=board, name="Local")  # shows the picker
    other_owner = User.objects.create_user(username="other")
    other_board = ContentBoard.objects.create(
        name="Other", slug="other", owner=other_owner
    )
    foreign_asset = Asset.objects.create(board=other_board, name="Foreign")
    form = PostForm(
        {
            "title": "X",
            "channel": "blog",
            "status": "drafting",
            "assets": [foreign_asset.pk],
        },
        campaign=campaign,
    )
    assert not form.is_valid()
    assert "assets" in form.errors


def test_post_form_accepts_same_board_asset(board, campaign):
    asset = Asset.objects.create(board=board, name="Mine")
    form = PostForm(
        {"title": "X", "channel": "blog", "status": "drafting", "assets": [asset.pk]},
        campaign=campaign,
    )
    assert form.is_valid()


def test_create_posts_carries_assets_to_each_channel(board, campaign):
    asset = Asset.objects.create(board=board, name="Shared asset")
    actor = User.objects.create_user(username="drafter2")
    form = PostCreateForm(
        {
            "title": "WithAsset",
            "channels": ["blog", "mastodon"],
            "status": "drafting",
            "assets": [asset.pk],
        },
        campaign=campaign,
    )
    assert form.is_valid(), form.errors
    posts = form.create_posts(actor)
    assert len(posts) == 2
    assert all(asset in p.assets.all() for p in posts)


def test_post_form_non_event_hides_offset(board, campaign):
    form = PostForm(campaign=campaign)
    assert "scheduled_at" in form.fields
    assert "anchor_offset_days" not in form.fields


def test_post_form_event_anchored_has_chooser_and_both_fields(board):
    import datetime

    ev = Campaign.objects.create(
        board=board, name="Anchored", event_date=datetime.date(2026, 5, 15)
    )
    form = PostForm(campaign=ev)
    assert "schedule_mode" in form.fields
    assert "anchor_offset_days" in form.fields
    assert "scheduled_at" in form.fields


def _event_campaign(board):
    import datetime

    return Campaign.objects.create(
        board=board, name="Anchored", event_date=datetime.date(2026, 5, 15)
    )


def test_post_create_offset_mode_clears_specific_date(auth_client, board):
    from zoneinfo import ZoneInfo

    ev = _event_campaign(board)
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": ev.slug},
        ),
        {
            "title": "Save the date",
            "channels": ["newsletter"],
            "status": "drafting",
            "schedule_mode": "offset",
            "anchor_offset_days": "-90",
            "scheduled_at": "2026-01-01T09:00",  # should be ignored
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    post = Post.objects.get(title="Save the date")
    assert post.anchor_offset_days == -90
    # Computed from the event date, not the ignored specific date.
    assert (
        post.scheduled_at.astimezone(ZoneInfo(board.timezone)).date().isoformat()
        == "2026-02-14"
    )


def test_post_create_date_mode_derives_offset(auth_client, board):
    ev = _event_campaign(board)
    resp = auth_client.post(
        reverse(
            "content_planner:post_create",
            kwargs={"board_slug": board.slug, "slug": ev.slug},
        ),
        {
            "title": "Pinned date",
            "channels": ["newsletter"],
            "status": "drafting",
            "schedule_mode": "date",
            "anchor_offset_days": "-99",  # should be ignored
            "scheduled_at": "2026-05-10T09:00",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    post = Post.objects.get(title="Pinned date")
    assert post.anchor_offset_days == -5  # derived from 2026-05-10 vs event 2026-05-15
    assert post.scheduled_at is not None


def test_post_form_accepts_date_only_schedule(board, campaign):
    form = PostForm(
        {
            "title": "X",
            "channel": "blog",
            "status": "drafting",
            "scheduled_at": "2026-07-01",
        },
        campaign=campaign,
    )
    assert form.is_valid()
