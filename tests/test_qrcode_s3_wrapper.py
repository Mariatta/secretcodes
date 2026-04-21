from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

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
    from qrcode_manager.s3_wrapper import S3Wrapper

    S3Wrapper()
    boto_session.session.Session.assert_called_once()


@override_settings(**AWS_OVERRIDES)
def test_upload_fileobj_passes_through(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    wrapper.upload_fileobj(b"data", "f.png", "image/png")
    wrapper.client.upload_fileobj.assert_called_once()
    _, kwargs = wrapper.client.upload_fileobj.call_args
    assert kwargs["ExtraArgs"]["ContentType"] == "image/png"
    assert kwargs["ExtraArgs"]["ACL"] == "public-read"


@override_settings(**AWS_OVERRIDES)
def test_upload_fileobj_accepts_extra_args(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    wrapper.upload_fileobj(b"data", "f.png", "image/png", extra_args={"Foo": "Bar"})
    _, kwargs = wrapper.client.upload_fileobj.call_args
    assert kwargs["ExtraArgs"]["Foo"] == "Bar"


@override_settings(**AWS_OVERRIDES)
def test_generate_presigned_url(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    wrapper.client.generate_presigned_url.return_value = "https://signed"
    assert wrapper.generate_presigned_url("f.png") == "https://signed"
    wrapper.client.generate_presigned_url.assert_called_once()


@override_settings(**AWS_OVERRIDES)
def test_generate_url_composes_path(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    assert wrapper.generate_url("f.png") == "https://s3.example.com/bucket/f.png"


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_default_path(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    with patch("qrcode_manager.s3_wrapper.qrcode") as mock_qrcode:
        mock_qrcode.make.return_value = MagicMock()
        result = wrapper.generate_qr("https://example.com", "f.png")
    assert "short_lived/qrcode/f.png" in result


@override_settings(**AWS_OVERRIDES)
def test_generate_qr_custom_path(boto_session):
    from qrcode_manager.s3_wrapper import S3Wrapper

    wrapper = S3Wrapper()
    with patch("qrcode_manager.s3_wrapper.qrcode") as mock_qrcode:
        mock_qrcode.make.return_value = MagicMock()
        result = wrapper.generate_qr("https://example.com", "f.png", path="custom/")
    assert "custom/f.png" in result
