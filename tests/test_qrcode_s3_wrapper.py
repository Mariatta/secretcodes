import io
import os
from unittest.mock import patch

import pytest
from django.test import override_settings
from PIL import Image

from qrcode_manager.s3_wrapper import S3Wrapper

AWS_OVERRIDES = dict(
    AWS_S3_ENDPOINT_URL="https://s3.example.com",
    AWS_ACCESS_KEY_ID="key",
    AWS_SECRET_ACCESS_KEY="secret",
    AWS_STORAGE_BUCKET_NAME="bucket",
    AWS_DEFAULT_ACL="public-read",
    AWS_S3_OBJECT_PARAMETERS={"CacheControl": "max-age=86400"},
)


@pytest.fixture
def boto_session():
    with patch("qrcode_manager.s3_wrapper.boto3") as mock_boto:
        yield mock_boto


@override_settings(**AWS_OVERRIDES)
def test_init_builds_client(boto_session):
    S3Wrapper()
    boto_session.session.Session.assert_called_once()


@override_settings(**AWS_OVERRIDES)
def test_upload_fileobj_passes_through(boto_session):
    wrapper = S3Wrapper()
    wrapper.upload_fileobj(b"data", "f.png", "image/png")
    wrapper.client.upload_fileobj.assert_called_once()
    _, kwargs = wrapper.client.upload_fileobj.call_args
    assert kwargs["ExtraArgs"]["ContentType"] == "image/png"
    assert kwargs["ExtraArgs"]["ACL"] == "public-read"


@override_settings(**AWS_OVERRIDES)
def test_upload_fileobj_accepts_extra_args(boto_session):
    wrapper = S3Wrapper()
    wrapper.upload_fileobj(b"data", "f.png", "image/png", extra_args={"Foo": "Bar"})
    _, kwargs = wrapper.client.upload_fileobj.call_args
    assert kwargs["ExtraArgs"]["Foo"] == "Bar"


@override_settings(**AWS_OVERRIDES)
def test_generate_presigned_url(boto_session):
    wrapper = S3Wrapper()
    wrapper.client.generate_presigned_url.return_value = "https://signed"
    assert wrapper.generate_presigned_url("f.png") == "https://signed"
    wrapper.client.generate_presigned_url.assert_called_once()


@override_settings(**AWS_OVERRIDES)
def test_generate_url_composes_path(boto_session):
    wrapper = S3Wrapper()
    assert wrapper.generate_url("f.png") == "https://s3.example.com/bucket/f.png"


@override_settings(**AWS_OVERRIDES)
def test_delete_calls_delete_object(boto_session):
    wrapper = S3Wrapper()
    wrapper.delete("some/key.png")
    wrapper.client.delete_object.assert_called_once_with(
        Bucket="bucket", Key="some/key.png"
    )


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_default_path(boto_session):
    wrapper = S3Wrapper()
    result = wrapper.generate_qr("https://example.com", "f.png")
    assert "short_lived/qrcode/f.png" in result


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_custom_path(boto_session):
    wrapper = S3Wrapper()
    result = wrapper.generate_qr("https://example.com", "f.png", path="custom/")
    assert "custom/f.png" in result


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_passes_styling_to_builder(boto_session):
    wrapper = S3Wrapper()
    with patch("qrcode_manager.s3_wrapper.build_qr_png") as mock_build:
        mock_build.return_value = io.BytesIO(b"png")
        wrapper.generate_qr(
            "https://example.com",
            "f.png",
            fill_color="#112233",
            back_color="#ffeedd",
        )
    _, kwargs = mock_build.call_args
    assert kwargs["fill_color"] == "#112233"
    assert kwargs["back_color"] == "#ffeedd"
    assert kwargs["logo"] is None


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_downloads_logo_by_key(boto_session):
    wrapper = S3Wrapper()
    logo = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    logo_buffer = io.BytesIO()
    logo.save(logo_buffer, format="PNG")

    def fake_download(bucket, key, buffer):
        buffer.write(logo_buffer.getvalue())

    wrapper.client.download_fileobj.side_effect = fake_download
    with patch("qrcode_manager.s3_wrapper.build_qr_png") as mock_build:
        mock_build.return_value = io.BytesIO(b"png")
        wrapper.generate_qr("https://example.com", "f.png", logo_key="logos/f.logo.png")
    wrapper.client.download_fileobj.assert_called_once()
    _, kwargs = mock_build.call_args
    assert kwargs["logo"] is not None


@override_settings(**AWS_OVERRIDES)
def test_upload_logo_normalizes_to_png(boto_session):
    wrapper = S3Wrapper()
    logo = Image.new("RGB", (8, 8), (0, 128, 255))
    logo_buffer = io.BytesIO()
    logo.save(logo_buffer, format="JPEG")
    logo_buffer.seek(0)

    wrapper.upload_logo(logo_buffer, "logos/f.logo.png")

    args, kwargs = wrapper.client.upload_fileobj.call_args
    uploaded = args[0]
    assert Image.open(uploaded).format == "PNG"
    assert kwargs["ExtraArgs"]["ContentType"] == "image/png"


@override_settings(**AWS_OVERRIDES)
def test_download_fileobj_returns_rewound_buffer(boto_session):
    wrapper = S3Wrapper()

    def fake_download(bucket, key, buffer):
        buffer.write(b"bytes")

    wrapper.client.download_fileobj.side_effect = fake_download
    result = wrapper.download_fileobj("some/key")
    assert result.read() == b"bytes"


def test_local_mode_when_no_s3_endpoint(settings, tmp_path):
    """With no S3 endpoint (a dev machine without Spaces), the wrapper reads
    and writes the local filesystem under MEDIA_ROOT."""
    settings.AWS_S3_ENDPOINT_URL = ""
    settings.MEDIA_ROOT = str(tmp_path)
    settings.MEDIA_URL = "/media/"
    wrapper = S3Wrapper()
    assert wrapper.use_s3 is False

    target = os.path.join(str(tmp_path), "qrcode", "f.png")
    wrapper.upload_fileobj(io.BytesIO(b"PNGDATA"), target, "image/png")
    assert os.path.exists(target)
    assert wrapper.generate_url(target) == "/media/qrcode/f.png"
    assert wrapper.generate_presigned_url(target) == "/media/qrcode/f.png"
    assert wrapper.download_fileobj(target).read() == b"PNGDATA"

    wrapper.delete(target)
    assert not os.path.exists(target)
    wrapper.delete(target)  # already gone: no error


def test_local_mode_generate_qr_writes_file(settings, tmp_path):
    settings.AWS_S3_ENDPOINT_URL = ""
    settings.MEDIA_ROOT = str(tmp_path)
    settings.MEDIA_URL = "/media/"
    wrapper = S3Wrapper()
    path = os.path.join(str(tmp_path), "qrcode") + os.sep
    url = wrapper.generate_qr("https://example.com", "f.png", path=path)
    assert os.path.exists(os.path.join(str(tmp_path), "qrcode", "f.png"))
    assert url == "/media/qrcode/f.png"
