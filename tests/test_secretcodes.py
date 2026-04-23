import importlib

import pytest
from django.urls import reverse

from secretcodes.account_adapter import SecretCodesAccountAdapter


@pytest.mark.django_db
def test_index_view_renders(client):
    response = client.get(reverse("index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_privacy_page_renders(client):
    response = client.get(reverse("privacy"))
    assert response.status_code == 200
    assert b"Privacy Policy" in response.content
    assert b"freeBusy" in response.content


@pytest.mark.django_db
def test_terms_page_renders(client):
    response = client.get(reverse("terms"))
    assert response.status_code == 200
    assert b"Terms of Service" in response.content


@pytest.mark.django_db
def test_footer_links_to_privacy_and_terms(client):
    response = client.get(reverse("index"))
    assert reverse("privacy").encode() in response.content
    assert reverse("terms").encode() in response.content


@pytest.mark.django_db
def test_agents_page_renders(client):
    response = client.get(reverse("agents"))
    assert response.status_code == 200
    assert b"Model Context Protocol" in response.content
    assert b"check_availability" in response.content
    assert b"list_free_slots" in response.content


@pytest.mark.django_db
def test_landing_page_links_to_agents(client):
    response = client.get(reverse("index"))
    assert reverse("agents").encode() in response.content


@pytest.mark.django_db
def test_well_known_mcp_descriptor_returns_json(client):
    response = client.get(reverse("well_known_mcp"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = response.json()
    assert data["protocolVersion"] == "2024-11-05"
    assert data["name"] == "mariatta-availability"
    assert data["transport"] == "http"
    assert data["authentication"] == "none"
    tool_names = {tool["name"] for tool in data["tools"]}
    assert tool_names == {
        "check_availability",
        "list_free_slots",
        "get_busy_shadow",
        "get_booking_info",
    }
    assert data["endpoint"].endswith("/mcp/")
    assert data["documentation"].endswith("/agents/")
    assert data["limits"]["max_query_range_days"] == 14
    assert "60" in data["limits"]["rate"]


@pytest.mark.django_db
def test_privacy_page_does_not_expose_email(client):
    response = client.get(reverse("privacy"))
    assert b"github.com/Mariatta/secretcodes/issues" in response.content


@pytest.mark.django_db
def test_terms_page_does_not_expose_email(client):
    response = client.get(reverse("terms"))
    assert b"github.com/Mariatta/secretcodes/issues" in response.content


def test_account_adapter_signup_disabled():
    adapter = SecretCodesAccountAdapter()
    assert adapter.is_open_for_signup(request=None) is False


def test_asgi_application_importable():
    module = importlib.import_module("secretcodes.asgi")
    assert module.application is not None


def test_wsgi_application_importable():
    module = importlib.import_module("secretcodes.wsgi")
    assert module.application is not None
