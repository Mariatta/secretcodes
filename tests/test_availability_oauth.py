from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings
from django.urls import reverse

from availability.models import GoogleAccount, TrackedCalendar
from availability.services.oauth import (
    OAUTH_SCOPES,
    build_flow,
    fetch_user_email,
    revoke_token,
)

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


def _mock_response(status_code, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


def test_revoke_token_returns_true_for_empty_token():
    assert revoke_token("") is True


def test_revoke_token_returns_true_on_200():
    with patch(
        "availability.services.oauth.requests.post",
        return_value=_mock_response(200),
    ) as post:
        assert revoke_token("r-tok") is True
    post.assert_called_once()
    call = post.call_args
    assert call.args[0] == "https://oauth2.googleapis.com/revoke"
    assert call.kwargs["data"] == {"token": "r-tok"}


def test_revoke_token_returns_true_when_already_invalid():
    with patch(
        "availability.services.oauth.requests.post",
        return_value=_mock_response(400, {"error": "invalid_token"}),
    ):
        assert revoke_token("r-tok") is True


def test_revoke_token_returns_false_on_other_4xx_body():
    with patch(
        "availability.services.oauth.requests.post",
        return_value=_mock_response(400, {"error": "something_else"}),
    ):
        assert revoke_token("r-tok") is False


def test_revoke_token_returns_false_on_non_json_400():
    resp = MagicMock()
    resp.status_code = 400
    resp.json.side_effect = ValueError("no json")
    with patch("availability.services.oauth.requests.post", return_value=resp):
        assert revoke_token("r-tok") is False


def test_revoke_token_returns_false_on_5xx():
    with patch(
        "availability.services.oauth.requests.post",
        return_value=_mock_response(503),
    ):
        assert revoke_token("r-tok") is False


def test_revoke_token_returns_false_on_network_error():
    with patch(
        "availability.services.oauth.requests.post",
        side_effect=requests.ConnectionError(),
    ):
        assert revoke_token("r-tok") is False


@pytest.mark.django_db
def test_delete_account_requires_login(client):
    account = GoogleAccount.objects.create(
        label="x", email="x@y.com", refresh_token="r"
    )
    response = client.post(reverse("availability:delete_account", args=[account.pk]))
    assert response.status_code == 302
    assert "accounts/login" in response.url
    assert GoogleAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_delete_account_rejects_non_superuser(client, django_user_model):
    user = django_user_model.objects.create_user("regular", password="p")
    client.force_login(user)
    account = GoogleAccount.objects.create(
        label="x", email="x@y.com", refresh_token="r"
    )
    response = client.post(reverse("availability:delete_account", args=[account.pk]))
    assert response.status_code == 302
    assert "accounts/login" in response.url
    assert GoogleAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_delete_account_rejects_get(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    account = GoogleAccount.objects.create(
        label="x", email="x@y.com", refresh_token="r"
    )
    response = client.get(reverse("availability:delete_account", args=[account.pk]))
    assert response.status_code == 405
    assert GoogleAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_delete_account_404_for_unknown_id(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    response = client.post(reverse("availability:delete_account", args=[9999]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_account_revokes_at_google_and_removes_row(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    account = GoogleAccount.objects.create(
        label="personal", email="me@personal.com", refresh_token="r-tok"
    )
    TrackedCalendar.objects.create(
        account=account,
        google_calendar_id="primary",
        display_label="Primary",
        is_active=True,
    )

    with patch("availability.views.revoke_token", return_value=True) as revoke:
        response = client.post(
            reverse("availability:delete_account", args=[account.pk]),
            follow=True,
        )

    revoke.assert_called_once_with("r-tok")
    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse("availability:admin")
    assert not GoogleAccount.objects.filter(pk=account.pk).exists()
    assert not TrackedCalendar.objects.filter(account_id=account.pk).exists()
    assert b"Disconnected me@personal.com" in response.content


@pytest.mark.django_db
def test_delete_account_proceeds_when_revoke_fails(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "u", email="u@example.com", password="p"
    )
    client.force_login(user)
    account = GoogleAccount.objects.create(
        label="x", email="me@personal.com", refresh_token="r-tok"
    )

    with patch("availability.views.revoke_token", return_value=False):
        response = client.post(
            reverse("availability:delete_account", args=[account.pk]),
            follow=True,
        )

    assert response.status_code == 200
    assert not GoogleAccount.objects.filter(pk=account.pk).exists()
    assert b"Google&#x27;s revoke endpoint did" in response.content or (
        b"Google's revoke endpoint did" in response.content
    )


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
