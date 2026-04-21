import pytest
from django.conf import settings

from qrcode_manager.models import QRCode


@pytest.mark.django_db
def test_str_returns_description():
    qr = QRCode.objects.create(url="https://example.com", description="thing")
    assert str(qr) == "thing"


@pytest.mark.django_db
def test_qr_filename_uses_existing_filename():
    qr = QRCode.objects.create(
        url="https://example.com", description="thing", filename="existing.png"
    )
    assert qr.qr_filename == "existing.png"


@pytest.mark.django_db
def test_qr_filename_derives_from_description_when_blank():
    qr = QRCode.objects.create(url="https://example.com", description="thing")
    qr.filename = ""
    assert qr.qr_filename == "thing.png"
    assert qr.filename == "thing.png"


@pytest.mark.django_db
def test_get_qr_image_url_delegates_to_s3_wrapper(mock_s3_wrapper):
    qr = QRCode.objects.create(url="https://example.com", description="thing")
    mock_s3_wrapper.generate_url.return_value = "http://mocked/thing.png"
    assert qr.get_qr_image_url() == "http://mocked/thing.png"


@pytest.mark.django_db
def test_generate_qr_without_slug_uses_url(mock_s3_wrapper):
    QRCode.objects.create(url="https://example.com", description="no-slug")
    positional_urls = [c.args[0] for c in mock_s3_wrapper.generate_qr.call_args_list]
    assert "https://example.com" in positional_urls


@pytest.mark.django_db
def test_generate_qr_with_slug_uses_domain_and_slug(mock_s3_wrapper):
    QRCode.objects.create(
        url="https://example.com", description="with-slug", slug="abc"
    )
    positional_urls = [c.args[0] for c in mock_s3_wrapper.generate_qr.call_args_list]
    assert f"{settings.DOMAIN_NAME}/abc" in positional_urls


@pytest.mark.django_db
def test_basemodel_save_updates_modified_date():
    qr = QRCode.objects.create(url="https://example.com", description="one")
    original = qr.modified_date
    qr.description = "two"
    qr.save()
    assert qr.modified_date >= original
