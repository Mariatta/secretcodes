"""Export-as-JSON and create-from-chat import."""

import datetime
import json
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from content_planner.models import Asset, Campaign, ContentBoard, Post

User = get_user_model()
VAN = "America/Vancouver"


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
        name="B", slug="ie-board", owner=user, timezone=VAN
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def _export_url(board, campaign):
    return reverse(
        "content_planner:campaign_export",
        kwargs={"board_slug": board.slug, "slug": campaign.slug},
    )


def _import_url(board):
    return reverse(
        "content_planner:campaign_create_from_chat",
        kwargs={"board_slug": board.slug},
    )


# ---------------------------------------------------------------- export


def test_export_json_structure(auth_client, board, user, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="Launch")
    campaign.tags.set([board.tags.create(name="advocacy")])
    post = Post.objects.create(
        campaign=campaign,
        title="Announce",
        channel="mastodon",
        status="ready",
        created_by=user,
        scheduled_at=datetime.datetime(2026, 5, 30, 16, 0, tzinfo=ZoneInfo("UTC")),
    )
    asset = Asset.objects.create(
        board=board, name="Hero", file=SimpleUploadedFile("h.png", b"x")
    )
    post.assets.add(asset)

    resp = auth_client.get(_export_url(board, campaign))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    data = resp.json()
    assert data["campaign"]["name"] == "Launch"
    assert data["campaign"]["tags"] == ["advocacy"]
    assert data["posts"][0]["title"] == "Announce"
    assert data["posts"][0]["created_by"] == "owner"
    # 16:00 UTC is 09:00 in Vancouver (PDT)
    assert data["posts"][0]["scheduled_at"].startswith("2026-05-30T09:00:00")
    assert data["assets"][0]["name"] == "Hero"
    assert data["assets"][0]["file_url"]


def test_export_handles_nulls(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Empty")
    Post.objects.create(campaign=campaign, title="NoSched", channel="blog")
    Asset.objects.create(board=board, name="SrcOnly", source_url="https://x/y.png")
    resp = auth_client.get(_export_url(board, campaign))
    data = resp.json()
    assert data["campaign"]["event_date"] is None
    assert data["posts"][0]["scheduled_at"] is None
    assert data["posts"][0]["created_by"] is None
    # asset isn't attached to a post, so it isn't in the export
    assert data["assets"] == []


def test_export_html_wrapper(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="Viewable")
    resp = auth_client.get(_export_url(board, campaign), {"view": "html"})
    assert resp.status_code == 200
    assert b"Viewable" in resp.content
    assert b"Copy" in resp.content


# ---------------------------------------------------------------- import


def test_import_get_renders_form(auth_client, board):
    assert auth_client.get(_import_url(board)).status_code == 200


def test_import_non_event_campaign(auth_client, board, user):
    payload = {
        "campaign": {"name": "Blog series", "tags": ["advocacy"]},
        "posts": [
            {
                "title": "Part 1",
                "channel": "blog",
                "scheduled_at": "2026-05-30T00:00:00",
                "status": "published",  # ignored
            },
            {
                "title": "Announce",
                "channel": "mastodon",
                "scheduled_at": "2026-05-30T09:00:00",
            },
        ],
    }
    resp = auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    assert resp.status_code == 302
    campaign = Campaign.objects.get(name="Blog series")
    assert set(campaign.tags.values_list("name", flat=True)) == {"advocacy"}
    posts = list(campaign.posts.all())
    assert len(posts) == 2
    assert all(p.status == "drafting" for p in posts)  # status forced
    assert all(p.created_by == user for p in posts)
    blog = campaign.posts.get(channel="blog")
    assert blog.is_all_day is True  # default for blog
    assert blog.scheduled_at is not None
    assert campaign.posts.get(channel="mastodon").is_all_day is False


def test_import_event_anchored(auth_client, board):
    payload = {
        "campaign": {"name": "PyCon comms", "event_date": "2026-05-15"},
        "posts": [
            {
                "title": "Save the date",
                "channel": "newsletter",
                "anchor_offset_days": -90,
                "time_of_day": "09:00",
            }
        ],
    }
    resp = auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    assert resp.status_code == 302
    post = Post.objects.get(title="Save the date")
    assert post.anchor_offset_days == -90
    local = post.scheduled_at.astimezone(ZoneInfo(VAN))
    assert local.date() == datetime.date(2026, 2, 14)
    assert local.time() == datetime.time(9, 0)


def test_import_anchored_without_time_defaults_0900(auth_client, board):
    payload = {
        "campaign": {"name": "Ev", "event_date": "2026-05-15"},
        "posts": [{"title": "T", "channel": "newsletter", "anchor_offset_days": -1}],
    }
    auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    post = Post.objects.get(title="T")
    assert post.scheduled_at.astimezone(ZoneInfo(VAN)).time() == datetime.time(9, 0)


def test_import_event_campaign_post_without_dates(auth_client, board):
    payload = {
        "campaign": {"name": "Ev", "event_date": "2026-05-15"},
        "posts": [{"title": "TBD", "channel": "blog"}],
    }
    auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    post = Post.objects.get(title="TBD")
    assert post.scheduled_at is None
    assert post.anchor_offset_days is None


def test_import_aware_datetime_preserved(auth_client, board):
    payload = {
        "campaign": {"name": "Aware"},
        "posts": [
            {"title": "P", "channel": "x", "scheduled_at": "2026-05-30T09:00:00-07:00"}
        ],
    }
    auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    post = Post.objects.get(title="P")
    assert post.scheduled_at.astimezone(ZoneInfo(VAN)).hour == 9


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ("not json {", "Invalid JSON"),
        ('["a list"]', "must be an object"),
        ('{"posts": []}', "campaign.name"),
        ('{"campaign": {"name": "X"}}', "posts list"),
        (
            '{"campaign": {"name": "X", "event_date": "nope"}, "posts": []}',
            "event_date",
        ),
        (
            '{"campaign": {"name": "X"}, "posts": [{"channel": "blog"}]}',
            "needs a title",
        ),
        (
            '{"campaign": {"name": "X"}, "posts": [{"title": "T", "channel": "zzz"}]}',
            "Unknown channel",
        ),
    ],
)
def test_import_errors(auth_client, board, payload, fragment):
    resp = auth_client.post(_import_url(board), {"payload": payload})
    assert resp.status_code == 200
    assert not Campaign.objects.filter(board=board).exists()
    if fragment:
        assert fragment.encode() in resp.content


def test_import_bad_time_of_day_for_anchored(auth_client, board):
    payload = {
        "campaign": {"name": "Ev", "event_date": "2026-05-15"},
        "posts": [
            {
                "title": "T",
                "channel": "newsletter",
                "anchor_offset_days": -1,
                "time_of_day": "99:99",
            }
        ],
    }
    resp = auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    assert resp.status_code == 200
    assert b"time_of_day" in resp.content
    assert not Campaign.objects.filter(name="Ev").exists()  # rolled back


def test_import_bad_scheduled_at(auth_client, board):
    payload = {
        "campaign": {"name": "Bad"},
        "posts": [{"title": "T", "channel": "blog", "scheduled_at": "not-a-date"}],
    }
    resp = auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    assert resp.status_code == 200
    assert b"scheduled_at" in resp.content


def test_import_export_hashtags(auth_client, board):
    payload = {
        "campaign": {"name": "Tagged", "hashtags": "#PyLadiesCon"},
        "posts": [{"title": "P", "channel": "mastodon", "hashtags": "#python"}],
    }
    auth_client.post(_import_url(board), {"payload": json.dumps(payload)})
    campaign = Campaign.objects.get(name="Tagged")
    assert campaign.hashtags == "#PyLadiesCon"
    assert campaign.posts.get().hashtags == "#python"
    data = auth_client.get(_export_url(board, campaign)).json()
    assert data["campaign"]["hashtags"] == "#PyLadiesCon"
    assert data["posts"][0]["hashtags"] == "#python"


def test_export_import_round_trip(auth_client, board):
    source = Campaign.objects.create(board=board, name="Source", event_date=None)
    Post.objects.create(
        campaign=source, title="Orig", channel="blog", status="published"
    )
    exported = auth_client.get(_export_url(board, source)).json()
    # Feed the export straight back in as a new campaign.
    exported["campaign"]["name"] = "Imported copy"
    auth_client.post(_import_url(board), {"payload": json.dumps(exported)})
    copy = Campaign.objects.get(name="Imported copy")
    assert copy.posts.get().status == "drafting"  # never PUBLISHED on import
