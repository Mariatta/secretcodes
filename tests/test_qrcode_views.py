import io

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from qrcode_manager.models import QRCode


@pytest.fixture
def qr_slug_perm(db):
    ct = ContentType.objects.get_for_model(QRCode)
    return Permission.objects.get(codename="create_slug_qrcode", content_type=ct)


def _login_with_slug_access(client, django_user_model, qr_slug_perm, username="u"):
    user = django_user_model.objects.create_user(username, password="p")
    user.user_permissions.add(qr_slug_perm)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_qr_code_generator_get(client):
    response = client.get(reverse("qrcode_generator"))
    assert response.status_code == 200
    assert b"url" in response.content.lower()


@pytest.mark.django_db
def test_qr_code_generator_post_creates(client):
    response = client.post(
        reverse("qrcode_generator"),
        {"url": "https://example.com", "description": "new"},
    )
    assert response.status_code == 200
    assert QRCode.objects.filter(url="https://example.com").exists()


@pytest.mark.django_db
def test_qr_code_generator_post_reuses_existing(client):
    QRCode.objects.create(url="https://example.com", description="old")
    response = client.post(
        reverse("qrcode_generator"),
        {"url": "https://example.com", "description": "new"},
    )
    assert response.status_code == 200
    assert QRCode.objects.filter(url="https://example.com").count() == 1


@pytest.mark.django_db
def test_qr_code_generator_invalid_post(client):
    response = client.post(reverse("qrcode_generator"), {"url": "not-a-url"})
    assert response.status_code == 200
    assert not QRCode.objects.exists()


@pytest.mark.django_db
def test_slug_generator_requires_login(client):
    response = client.get(reverse("qrcode_slug_generator"))
    assert response.status_code == 302
    assert "accounts/login" in response.url


@pytest.mark.django_db
def test_slug_generator_redirects_without_perm(client, django_user_model):
    """A logged-in user without create_slug_qrcode is redirected to login
    by user_passes_test."""
    user = django_user_model.objects.create_user("noperm", password="p")
    client.force_login(user)
    response = client.get(reverse("qrcode_slug_generator"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_slug_generator_allowed_for_superuser(client, django_user_model):
    """Superusers bypass the permission check (user.has_perm returns True)."""
    user = django_user_model.objects.create_superuser("admin", password="p")
    client.force_login(user)
    response = client.get(reverse("qrcode_slug_generator"))
    assert response.status_code == 200


def test_slug_generator_get_authenticated(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.get(reverse("qrcode_slug_generator"))
    assert response.status_code == 200


def test_slug_generator_post_creates(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "new", "slug": "abc"},
    )
    assert response.status_code == 200
    qr = QRCode.objects.get(url="https://example.com")
    assert qr.slug == "abc"


def test_slug_generator_post_updates_missing_slug(
    client, django_user_model, qr_slug_perm
):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    QRCode.objects.create(url="https://example.com", description="existing")
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "newslug"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "newslug"


def test_slug_generator_post_changes_existing_slug(
    client, django_user_model, qr_slug_perm
):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    QRCode.objects.create(url="https://example.com", description="existing", slug="old")
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "new"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "new"


def test_slug_generator_post_same_slug_noop(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    QRCode.objects.create(
        url="https://example.com", description="existing", slug="same"
    )
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "same"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "same"


def test_slug_generator_invalid_post(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(reverse("qrcode_slug_generator"), {"url": "bad"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_url_reverse_redirects_and_increments(client):
    qr = QRCode.objects.create(
        url="https://example.com", description="redir", slug="go"
    )
    response = client.get(reverse("url_reverse", args=["go"]))
    assert response.status_code == 302
    assert response.url == "https://example.com"
    qr.refresh_from_db()
    assert qr.visit_count == 1
    assert qr.last_visited is not None


@pytest.mark.django_db
def test_url_reverse_unknown_slug_404s(client):
    response = client.get(reverse("url_reverse", args=["nope"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_legacy_url_301_redirects_to_qr_namespace(client):
    QRCode.objects.create(url="https://example.com", description="old", slug="oldlink")
    response = client.get(reverse("legacy_url_reverse", args=["oldlink"]))
    assert response.status_code == 301
    assert response.url == reverse("url_reverse", args=["oldlink"])


@pytest.mark.django_db
def test_legacy_url_unknown_slug_404s(client):
    response = client.get(reverse("legacy_url_reverse", args=["nope"]))
    assert response.status_code == 404


def _png_upload(name="logo.png", size=(16, 16), color=(255, 0, 0, 255)):
    """A small in-memory PNG suitable for ImageField uploads."""
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_style_preview_requires_login(client):
    response = client.post(reverse("qrcode_preview"), {"url": "https://example.com"})
    assert response.status_code == 302
    assert "accounts/login" in response.url


def test_style_preview_rejects_get(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.get(reverse("qrcode_preview"))
    assert response.status_code == 405


def test_style_preview_returns_png(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_preview"),
        {
            "url": "https://example.com",
            "slug": "abc",
            "fill_color": "#112233",
            "back_color": "#ffeedd",
        },
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert not QRCode.objects.exists()


def test_style_preview_with_logo(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_preview"),
        {"url": "https://example.com", "logo": _png_upload()},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"


def test_style_preview_invalid_returns_400(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(reverse("qrcode_preview"), {"url": "not-a-url"})
    assert response.status_code == 400
    assert "url" in response.json()["errors"]


def test_slug_generator_saves_styling(
    client, django_user_model, qr_slug_perm, mock_s3_wrapper
):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_slug_generator"),
        {
            "url": "https://example.com",
            "description": "styled",
            "slug": "abc",
            "fill_color": "#112233",
            "back_color": "#ffeedd",
            "logo": _png_upload(),
        },
    )
    assert response.status_code == 200
    qr = QRCode.objects.get(url="https://example.com")
    assert qr.fill_color == "#112233"
    assert qr.back_color == "#ffeedd"
    assert qr.logo_filename == "styled.png.logo.png"
    mock_s3_wrapper.upload_logo.assert_called_once()


def test_slug_generator_defaults_styling_when_omitted(
    client, django_user_model, qr_slug_perm
):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "plain", "slug": "abc"},
    )
    qr = QRCode.objects.get(url="https://example.com")
    assert qr.fill_color == "#000000"
    assert qr.back_color == "#ffffff"
    assert qr.logo_filename == ""


def test_style_preview_with_module_and_mask(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_preview"),
        {
            "url": "https://example.com",
            "module_style": "rounded",
            "color_mask_style": "radial_gradient",
            "fill_color": "#112233",
            "gradient_color": "#445566",
        },
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_style_preview_rejects_unknown_style(client, django_user_model, qr_slug_perm):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    response = client.post(
        reverse("qrcode_preview"),
        {"url": "https://example.com", "module_style": "triangle"},
    )
    assert response.status_code == 400
    assert "module_style" in response.json()["errors"]


def test_slug_generator_saves_module_and_mask(
    client, django_user_model, qr_slug_perm, mock_s3_wrapper
):
    _login_with_slug_access(client, django_user_model, qr_slug_perm)
    client.post(
        reverse("qrcode_slug_generator"),
        {
            "url": "https://example.com",
            "description": "styled",
            "slug": "abc",
            "module_style": "circle",
            "color_mask_style": "square_gradient",
            "fill_color": "#112233",
            "gradient_color": "#445566",
        },
    )
    qr = QRCode.objects.get(url="https://example.com")
    assert qr.module_style == "circle"
    assert qr.color_mask_style == "square_gradient"
    assert qr.gradient_color == "#445566"
