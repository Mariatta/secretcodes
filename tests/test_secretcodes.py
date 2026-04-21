import importlib

import pytest
from django.urls import reverse

from secretcodes.account_adapter import SecretCodesAccountAdapter


@pytest.mark.django_db
def test_index_view_renders(client):
    response = client.get(reverse("index"))
    assert response.status_code == 200


def test_account_adapter_signup_disabled():
    adapter = SecretCodesAccountAdapter()
    assert adapter.is_open_for_signup(request=None) is False


def test_asgi_application_importable():
    module = importlib.import_module("secretcodes.asgi")
    assert module.application is not None


def test_wsgi_application_importable():
    module = importlib.import_module("secretcodes.wsgi")
    assert module.application is not None
