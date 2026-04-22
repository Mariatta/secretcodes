import pytest
from django.urls import reverse

from qrcode_manager.models import QRCode


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
def test_slug_generator_get_authenticated(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
    response = client.get(reverse("qrcode_slug_generator"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_slug_generator_post_creates(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "new", "slug": "abc"},
    )
    assert response.status_code == 200
    qr = QRCode.objects.get(url="https://example.com")
    assert qr.slug == "abc"


@pytest.mark.django_db
def test_slug_generator_post_updates_missing_slug(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
    QRCode.objects.create(url="https://example.com", description="existing")
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "newslug"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "newslug"


@pytest.mark.django_db
def test_slug_generator_post_changes_existing_slug(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
    QRCode.objects.create(url="https://example.com", description="existing", slug="old")
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "new"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "new"


@pytest.mark.django_db
def test_slug_generator_post_same_slug_noop(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
    QRCode.objects.create(
        url="https://example.com", description="existing", slug="same"
    )
    response = client.post(
        reverse("qrcode_slug_generator"),
        {"url": "https://example.com", "description": "x", "slug": "same"},
    )
    assert response.status_code == 200
    assert QRCode.objects.get(url="https://example.com").slug == "same"


@pytest.mark.django_db
def test_slug_generator_invalid_post(client, django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    client.force_login(user)
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
