"""Asset library: views, form, and the post-picker archived exclusion."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from content_planner.forms import PostForm
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
    u = User.objects.create_user(username="assetowner", password="pw")
    u.user_permissions.add(access_perm)
    return u


@pytest.fixture
def board(user):
    return ContentBoard.objects.create(name="B", slug="assetboard", owner=user)


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def _url(name, board, **kwargs):
    return reverse(
        f"content_planner:{name}", kwargs={"board_slug": board.slug, **kwargs}
    )


# ------------------------------------------------------------------ list


def test_asset_list_empty(auth_client, board):
    resp = auth_client.get(_url("asset_list", board))
    assert resp.status_code == 200
    assert b"No assets yet" in resp.content


def test_asset_list_shows_active_and_archived(auth_client, board):
    Asset.objects.create(board=board, name="Active one", status="ready")
    Asset.objects.create(board=board, name="Old one", status="archived")
    resp = auth_client.get(_url("asset_list", board))
    assert resp.status_code == 200
    assert b"Active one" in resp.content
    assert b"Old one" in resp.content
    assert b"Archived" in resp.content


# ------------------------------------------------------------------ create


def test_asset_create_get(auth_client, board):
    assert auth_client.get(_url("asset_create", board)).status_code == 200


def test_asset_create_with_source_url(auth_client, board):
    resp = auth_client.post(
        _url("asset_create", board),
        {
            "name": "Hero",
            "kind": "image",
            "status": "drafting",
            "source_url": "https://example.com/x.png",
            "caption": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    asset = Asset.objects.get(name="Hero")
    assert asset.board == board
    assert asset.source_url == "https://example.com/x.png"


def test_asset_create_with_file(auth_client, board, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile("pic.png", b"binarydata", content_type="image/png")
    resp = auth_client.post(
        _url("asset_create", board),
        {
            "name": "Uploaded",
            "kind": "image",
            "status": "drafting",
            "source_url": "",
            "caption": "",
            "notes": "",
            "file": upload,
        },
    )
    assert resp.status_code == 302
    assert Asset.objects.get(name="Uploaded").file


def test_asset_create_invalid(auth_client, board):
    resp = auth_client.post(_url("asset_create", board), {"name": ""})
    assert resp.status_code == 200
    assert not Asset.objects.filter(name="").exists()


# ------------------------------------------------------------------ edit


def test_asset_edit_get(auth_client, board):
    asset = Asset.objects.create(board=board, name="EditGet")
    assert auth_client.get(_url("asset_edit", board, pk=asset.pk)).status_code == 200


def test_asset_edit_post(auth_client, board):
    asset = Asset.objects.create(board=board, name="Before", status="drafting")
    resp = auth_client.post(
        _url("asset_edit", board, pk=asset.pk),
        {
            "name": "After",
            "kind": "image",
            "status": "ready",
            "source_url": "",
            "caption": "",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    asset.refresh_from_db()
    assert asset.name == "After"
    assert asset.status == "ready"


def test_asset_edit_invalid(auth_client, board):
    asset = Asset.objects.create(board=board, name="Keep")
    resp = auth_client.post(_url("asset_edit", board, pk=asset.pk), {"name": ""})
    assert resp.status_code == 200


# ------------------------------------------------------------------ archive


def test_asset_archive(auth_client, board):
    asset = Asset.objects.create(board=board, name="ToArchive", status="ready")
    resp = auth_client.post(_url("asset_archive", board, pk=asset.pk))
    assert resp.status_code == 302
    asset.refresh_from_db()
    assert asset.status == "archived"


# ------------------------------------------------------------- post picker


def test_post_picker_excludes_archived(board):
    campaign = Campaign.objects.create(board=board, name="C")
    active = Asset.objects.create(board=board, name="Active", status="ready")
    Asset.objects.create(board=board, name="Gone", status="archived")
    form = PostForm(campaign=campaign)
    assert "assets" in form.fields
    queryset = form.fields["assets"].queryset
    assert active in queryset
    assert not queryset.filter(status="archived").exists()


def test_post_picker_queryset_excludes_archived(board):
    campaign = Campaign.objects.create(board=board, name="C")
    Asset.objects.create(board=board, name="Gone", status="archived")
    form = PostForm(campaign=campaign)
    assert "assets" in form.fields
    assert not form.fields["assets"].queryset.exists()


# ----------------------------------------------- post-page picker + upload


def test_render_asset_tag_modes(board):
    from content_planner.templatetags.content_planner_tags import render_asset

    asset = Asset.objects.create(board=board, name="Hero", caption="Alt text")
    assert render_asset(asset) == {"asset": asset, "show_caption": False}
    assert render_asset(asset, show_caption=True)["show_caption"] is True


def test_post_detail_image_asset_has_lightbox(auth_client, board, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="C")
    asset = Asset.objects.create(
        board=board, name="Hero", file=SimpleUploadedFile("h.png", b"x")
    )
    post = Post.objects.create(campaign=campaign, title="P", channel="blog")
    post.assets.add(asset)
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
    assert b"data-lightbox=" in resp.content


def test_post_detail_shows_asset_caption_and_edit_link(auth_client, board):
    campaign = Campaign.objects.create(board=board, name="C")
    asset = Asset.objects.create(
        board=board, name="Hero", caption="A photo of the venue"
    )
    post = Post.objects.create(campaign=campaign, title="P", channel="blog")
    post.assets.add(asset)
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
    content = resp.content.decode()
    assert "A photo of the venue" in content  # caption shown
    assert f"sc-cap-{asset.pk}" in content  # copyable caption element
    assert (
        reverse(
            "content_planner:asset_edit",
            kwargs={"board_slug": board.slug, "pk": asset.pk},
        )
        in content
    )  # title links to edit


def test_post_create_renders_thumbnail_picker(auth_client, board, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="C")
    Asset.objects.create(
        board=board, name="Pickme", file=SimpleUploadedFile("p.png", b"x")
    )
    resp = auth_client.get(_url("post_create", board, slug=campaign.slug))
    assert resp.status_code == 200
    assert b"Pickme" in resp.content
    assert b'name="assets"' in resp.content


def test_post_edit_marks_attached_asset_checked(auth_client, board, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="C")
    asset = Asset.objects.create(
        board=board, name="Sel", file=SimpleUploadedFile("s.png", b"x")
    )
    post = Post.objects.create(campaign=campaign, title="P", channel="blog")
    post.assets.add(asset)
    resp = auth_client.get(
        _url("post_edit", board, slug=campaign.slug, post_slug=post.slug)
    )
    content = resp.content.decode()
    assert f'value="{asset.pk}"' in content
    assert "checked" in content


def test_post_edit_inline_upload_creates_and_attaches(
    auth_client, board, tmp_path, settings
):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="P", channel="blog")
    resp = auth_client.post(
        _url("post_edit", board, slug=campaign.slug, post_slug=post.slug),
        {
            "title": "P",
            "channel": "blog",
            "status": "drafting",
            "expected_asset": "",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
            "new_asset": SimpleUploadedFile("new.png", b"data"),
        },
    )
    assert resp.status_code == 302
    assert post.assets.get().name == "new.png"


def test_post_create_inline_upload_attaches_to_all_channels(
    auth_client, board, tmp_path, settings
):
    settings.MEDIA_ROOT = str(tmp_path)
    campaign = Campaign.objects.create(board=board, name="C")
    resp = auth_client.post(
        _url("post_create", board, slug=campaign.slug),
        {
            "title": "Multi",
            "channels": ["blog", "mastodon"],
            "status": "drafting",
            "expected_asset": "",
            "body_snippet": "",
            "draft_url": "",
            "published_url": "",
            "notes": "",
            "new_asset": SimpleUploadedFile("shared.png", b"data"),
        },
    )
    assert resp.status_code == 302
    posts = Post.objects.filter(title="Multi")
    assert posts.count() == 2
    attached = {p.assets.get().pk for p in posts}
    assert len(attached) == 1  # the same single uploaded asset on both
    assert Asset.objects.filter(board=board, name="shared.png").count() == 1


# --------------------------------------------------------- media previews


def test_asset_is_image_from_file(board):
    asset = Asset(board=board, name="Pic")
    asset.file = "content_planner/assets/photo.PNG"
    assert asset.is_image is True
    assert asset.is_video is False
    assert asset.media_url.endswith("photo.PNG")


def test_asset_is_video_from_file(board):
    asset = Asset(board=board, name="Clip")
    asset.file = "content_planner/assets/movie.mp4"
    assert asset.is_video is True
    assert asset.is_image is False


def test_asset_non_media_file(board):
    asset = Asset(board=board, name="Doc")
    asset.file = "content_planner/assets/handout.pdf"
    assert asset.is_image is False
    assert asset.is_video is False


def test_asset_is_image_from_source_url(board):
    asset = Asset(board=board, name="Remote", source_url="https://ex.com/a.jpg?v=2")
    assert asset.is_image is True
    assert asset.media_url == "https://ex.com/a.jpg?v=2"


def test_asset_without_media(board):
    asset = Asset(board=board, name="Nothing")
    assert asset.media_url == ""
    assert asset.is_image is False
    assert asset.is_video is False
