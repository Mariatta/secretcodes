import os
from unittest.mock import MagicMock

import pytest
from django.core.cache import cache

os.environ.setdefault("FERNET_KEY", "kTdjP9joWZr9JfnWHGmcQOOPxFEKfCB3_Hx7OgHD6LU=")


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear Django cache between tests so ratelimit counters don't bleed."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _assume_connected_calendars(monkeypatch):
    """Tests assume at least one connected calendar by default.

    Tests exercising the disconnected UX override at the relevant import
    site — `availability.views.has_active_calendars` for web/JSON views,
    `availability.services.mcp.has_active_calendars` for MCP tools.
    """
    monkeypatch.setattr("availability.views.has_active_calendars", lambda: True)
    monkeypatch.setattr("availability.services.mcp.has_active_calendars", lambda: True)


@pytest.fixture(autouse=True)
def mock_s3_wrapper(monkeypatch):
    mock_class = MagicMock()
    mock_instance = mock_class.return_value
    mock_instance.generate_qr.return_value = "http://mocked/qr.png"
    mock_instance.generate_url.return_value = "http://mocked/qr.png"
    monkeypatch.setattr("qrcode_manager.models.S3Wrapper", mock_class)
    return mock_instance
