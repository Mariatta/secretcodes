import os
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import Permission
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


@pytest.fixture
def surveys_user_perm(db):
    """The ``access_surveys`` permission — required for any creator surface."""
    return Permission.objects.get(
        codename="access_surveys", content_type__app_label="surveys"
    )


@pytest.fixture
def surveys_create_perm(db):
    """The ``create_surveys`` permission — required to start a new survey."""
    return Permission.objects.get(
        codename="create_surveys", content_type__app_label="surveys"
    )


@pytest.fixture(autouse=True)
def mock_s3_wrapper(monkeypatch, settings):
    """The S3 wrapper is replaced with a MagicMock so QR generation
    doesn't try to hit DigitalOcean Spaces. ``AWS_S3_ENDPOINT_URL`` is
    also stubbed so code that gates on the setting (e.g.
    ``surveys.services.publishing._s3_configured``) treats the test
    environment as configured."""
    mock_class = MagicMock()
    mock_instance = mock_class.return_value
    mock_instance.generate_qr.return_value = "http://mocked/qr.png"
    mock_instance.generate_url.return_value = "http://mocked/qr.png"
    monkeypatch.setattr("qrcode_manager.models.S3Wrapper", mock_class)
    settings.AWS_S3_ENDPOINT_URL = "http://mocked.test"
    return mock_instance
