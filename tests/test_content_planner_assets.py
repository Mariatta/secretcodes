"""Asset library: views, form, and the post-picker archived exclusion."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from content_planner.forms import PostForm
from content_planner.models import Asset, Campaign, ContentBoard

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


def test_post_picker_hidden_when_only_archived(board):
    campaign = Campaign.objects.create(board=board, name="C")
    Asset.objects.create(board=board, name="Gone", status="archived")
    form = PostForm(campaign=campaign)
    assert "assets" not in form.fields
