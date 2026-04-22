from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.urls import reverse

from availability.models import GoogleAccount, TrackedCalendar
from availability.services.oauth import OAUTH_SCOPES, build_flow, fetch_user_email

OAUTH_SETTINGS = dict(
    GOOGLE_CLIENT_ID="cid",
    GOOGLE_CLIENT_SECRET="csecret",
    GOOGLE_OAUTH_REDIRECT_URI="https://example.com/availability/oauth/callback/",
)


@override_settings(**OAUTH_SETTINGS)
def test_build_flow_uses_client_settings_and_scopes():
    flow = build_flow()
    assert flow.client_config["client_id"] == "cid"
    assert flow.client_config["client_secret"] == "csecret"
    assert flow.redirect_uri == OAUTH_SETTINGS["GOOGLE_OAUTH_REDIRECT_URI"]
    assert set(OAUTH_SCOPES).issubset(set(flow.oauth2session.scope))


def test_fetch_user_email_extracts_email():
    credentials = MagicMock()
    service = MagicMock()
    service.userinfo().get().execute.return_value = {"email": "me@example.com"}
    with patch("availability.services.oauth.build", return_value=service):
        assert fetch_user_email(credentials) == "me@example.com"


@pytest.mark.django_db
def test_admin_page_requires_login(client):
    response = client.get(reverse("availability:admin"))
    assert response.status_code == 302
    assert "accounts/login" in response.url


@pytest.mark.django_db
def test_admin_page_rejects_non_superuser(client, django_user_model):
    user = django_user_model.objects.create_user("regular", password="p")
    client.force_login(user)
    response = client.get(reverse("availability:admin"))
    assert response.status_code == 302
    assert "accounts/login" in response.url


@pytest.mark.django_db
def test_oauth_start_rejects_non_superuser(client, django_user_model):
    user = django_user_model.objects.create_user("regular", password="p")
    client.force_login(user)
    response = client.get(reverse("availability:oauth_start"))
    assert response.status_code == 302
    assert "accounts/login" in response.url


@pytest.mark.django_db
def test_admin_page_shows_no_accounts_message(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.get(reverse("availability:admin"))
    assert response.status_code == 200
    assert b"No Google accounts connected yet" in response.content


@pytest.mark.django_db
def test_admin_page_lists_connected_accounts(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    GoogleAccount.objects.create(
        label="personal", email="me@personal.com", refresh_token="r1"
    )
    response = client.get(reverse("availability:admin"))
    assert b"personal" in response.content
    assert b"me@personal.com" in response.content


@pytest.mark.django_db
def test_oauth_start_requires_login(client):
    response = client.get(reverse("availability:oauth_start"))
    assert response.status_code == 302
    assert "accounts/login" in response.url


@pytest.mark.django_db
@override_settings(**OAUTH_SETTINGS)
def test_oauth_start_redirects_to_google_and_stores_state(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.get(reverse("availability:oauth_start"))
    assert response.status_code == 302
    assert "accounts.google.com" in response.url
    assert "availability_oauth_state" in client.session
    assert "availability_code_verifier" in client.session
    assert client.session["availability_code_verifier"]


@pytest.mark.django_db
@override_settings(**OAUTH_SETTINGS)
def test_oauth_start_sends_pkce_code_challenge(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.get(reverse("availability:oauth_start"))
    assert "code_challenge=" in response.url
    assert "code_challenge_method=S256" in response.url


@pytest.mark.django_db
@override_settings(**OAUTH_SETTINGS)
def test_oauth_callback_creates_account_and_primary_calendar(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    session = client.session
    session["availability_oauth_state"] = "state123"
    session["availability_code_verifier"] = "verifier-xyz"
    session.save()

    flow = MagicMock()
    flow.credentials.refresh_token = "r-new"
    flow.credentials.scopes = OAUTH_SCOPES

    with patch("availability.views.build_flow", return_value=flow), patch(
        "availability.views.fetch_user_email", return_value="me@example.com"
    ):
        response = client.get(
            reverse("availability:oauth_callback"),
            {"code": "auth-code", "state": "state123"},
        )

    assert response.status_code == 302
    assert response.url == reverse("availability:admin")
    assert flow.code_verifier == "verifier-xyz"
    account = GoogleAccount.objects.get(email="me@example.com")
    assert account.refresh_token == "r-new"
    assert account.label == "me"
    assert account.scopes_granted == OAUTH_SCOPES
    assert TrackedCalendar.objects.filter(
        account=account, google_calendar_id="primary"
    ).exists()


@pytest.mark.django_db
@override_settings(**OAUTH_SETTINGS)
def test_oauth_callback_updates_existing_account(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    GoogleAccount.objects.create(
        label="old", email="me@example.com", refresh_token="r-old"
    )
    session = client.session
    session["availability_oauth_state"] = "state123"
    session["availability_code_verifier"] = "v"
    session.save()

    flow = MagicMock()
    flow.credentials.refresh_token = "r-new"
    flow.credentials.scopes = OAUTH_SCOPES

    with patch("availability.views.build_flow", return_value=flow), patch(
        "availability.views.fetch_user_email", return_value="me@example.com"
    ):
        client.get(
            reverse("availability:oauth_callback"),
            {"code": "auth-code", "state": "state123"},
        )

    account = GoogleAccount.objects.get(email="me@example.com")
    assert account.refresh_token == "r-new"
    assert GoogleAccount.objects.filter(email="me@example.com").count() == 1


@pytest.mark.django_db
def test_oauth_callback_rejects_mismatched_state(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    session = client.session
    session["availability_oauth_state"] = "real-state"
    session.save()

    response = client.get(
        reverse("availability:oauth_callback"),
        {"code": "c", "state": "wrong-state"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_oauth_callback_rejects_missing_state(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.get(
        reverse("availability:oauth_callback"), {"code": "c", "state": "x"}
    )
    assert response.status_code == 400


@pytest.mark.django_db
@override_settings(**OAUTH_SETTINGS)
def test_oauth_callback_rejects_missing_code(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    session = client.session
    session["availability_oauth_state"] = "s"
    session["availability_code_verifier"] = "v"
    session.save()
    response = client.get(reverse("availability:oauth_callback"), {"state": "s"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_landing_page_shows_manage_link_for_superuser(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.get(reverse("index"))
    assert reverse("availability:admin").encode() in response.content


@pytest.mark.django_db
def test_landing_page_hides_manage_link_from_regular_user(client, django_user_model):
    user = django_user_model.objects.create_user("regular", password="p")
    client.force_login(user)
    response = client.get(reverse("index"))
    assert reverse("availability:admin").encode() not in response.content


@pytest.mark.django_db
def test_landing_page_hides_manage_link_when_anonymous(client):
    response = client.get(reverse("index"))
    assert reverse("availability:admin").encode() not in response.content
