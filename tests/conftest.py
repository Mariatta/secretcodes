import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("FERNET_KEY", "kTdjP9joWZr9JfnWHGmcQOOPxFEKfCB3_Hx7OgHD6LU=")


@pytest.fixture(autouse=True)
def mock_s3_wrapper(monkeypatch):
    mock_class = MagicMock()
    mock_instance = mock_class.return_value
    mock_instance.generate_qr.return_value = "http://mocked/qr.png"
    mock_instance.generate_url.return_value = "http://mocked/qr.png"
    monkeypatch.setattr("qrcode_manager.models.S3Wrapper", mock_class)
    return mock_instance
