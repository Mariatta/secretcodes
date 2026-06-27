import io

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

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
def test_generate_qr_with_slug_uses_qr_namespace(mock_s3_wrapper):
    QRCode.objects.create(
        url="https://example.com", description="with-slug", slug="abc"
    )
    positional_urls = [c.args[0] for c in mock_s3_wrapper.generate_qr.call_args_list]
    assert f"{settings.DOMAIN_NAME}/qr/abc" in positional_urls


@pytest.mark.django_db
def test_basemodel_save_updates_modified_date():
    qr = QRCode.objects.create(url="https://example.com", description="one")
    original = qr.modified_date
    qr.description = "two"
    qr.save()
    assert qr.modified_date >= original


@pytest.mark.django_db
def test_save_rejects_reserved_slug():
    with pytest.raises(ValidationError):
        QRCode.objects.create(
            url="https://example.com", description="x", slug="availability"
        )


@pytest.mark.django_db
def test_clean_rejects_reserved_slug():
    qr = QRCode(url="https://example.com", description="x", slug="admin")
    with pytest.raises(ValidationError) as excinfo:
        qr.clean()
    assert "slug" in excinfo.value.message_dict


@pytest.mark.django_db
def test_clean_passes_for_non_reserved_slug():
    qr = QRCode(url="https://example.com", description="x", slug="mytalk")
    qr.clean()


@pytest.mark.django_db
def test_generate_qr_passes_styling(mock_s3_wrapper):
    QRCode.objects.create(
        url="https://example.com",
        description="styled",
        fill_color="#112233",
        back_color="#ffeedd",
    )
    _, kwargs = mock_s3_wrapper.generate_qr.call_args
    assert kwargs["fill_color"] == "#112233"
    assert kwargs["back_color"] == "#ffeedd"
    assert kwargs["logo_key"] == ""


@pytest.mark.django_db
def test_attach_logo_uploads_and_sets_filename(mock_s3_wrapper):
    qr = QRCode(url="https://example.com", description="logo")
    qr.attach_logo(io.BytesIO(b"fake"))
    assert qr.logo_filename == "logo.png.logo.png"
    mock_s3_wrapper.upload_logo.assert_called_once()
    _, key = mock_s3_wrapper.upload_logo.call_args.args
    assert key.endswith("/qrcode/logos/logo.png.logo.png")
    qr.save()
    _, kwargs = mock_s3_wrapper.generate_qr.call_args
    assert kwargs["logo_key"] == qr.logo_key


@pytest.mark.django_db
def test_logo_key_empty_without_logo():
    qr = QRCode(url="https://example.com", description="plain")
    assert qr.logo_key == ""


@pytest.mark.django_db
def test_generate_qr_passes_module_and_mask_styles(mock_s3_wrapper):
    QRCode.objects.create(
        url="https://example.com",
        description="styled",
        module_style="rounded",
        color_mask_style="radial_gradient",
        gradient_color="#445566",
    )
    _, kwargs = mock_s3_wrapper.generate_qr.call_args
    assert kwargs["module_style"] == "rounded"
    assert kwargs["color_mask_style"] == "radial_gradient"
    assert kwargs["gradient_color"] == "#445566"


@pytest.mark.django_db
def test_style_defaults_on_plain_create(mock_s3_wrapper):
    qr = QRCode.objects.create(url="https://example.com", description="plain")
    assert qr.module_style == "square"
    assert qr.color_mask_style == "solid"
