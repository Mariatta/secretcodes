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


def test_account_adapter_signup_disabled():
    adapter = SecretCodesAccountAdapter()
    assert adapter.is_open_for_signup(request=None) is False


def test_asgi_application_importable():
    module = importlib.import_module("secretcodes.asgi")
    assert module.application is not None


def test_wsgi_application_importable():
    module = importlib.import_module("secretcodes.wsgi")
    assert module.application is not None
