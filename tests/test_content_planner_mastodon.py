"""Mastodon connector: registration, OAuth, media processing, publishing.

Every HTTP call is mocked with `responses`. The point of these tests is the
sequencing Mastodon requires — register once per instance, wait for media to
finish converting, send the idempotency key — not that `requests` works.
"""

import pytest
import requests
import responses
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from content_planner.connectors import (
    AssetRef,
    PermanentPublishError,
    PublishPayload,
    TransientPublishError,
    transport,
)
from content_planner.connectors.mastodon import (
    FALLBACK_MAX_CHARS,
    MEDIA_POLL_ATTEMPTS,
    MastodonConnector,
    read_instance_limits,
    register_app,
)
from content_planner.models import MastodonApp, Platform, PublishingAccount

User = get_user_model()

HOST = "fosstodon.org"
API = f"https://{HOST}"


@pytest.fixture
def user(db):
    person = User.objects.create_user(username="owner", password="pw")
    person.user_permissions.add(
        Permission.objects.get(
            codename="access_content_planner",
            content_type__app_label="content_planner",
        )
    )
    return person


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def account(user):
    return PublishingAccount.objects.create(
        owner=user,
        platform=Platform.MASTODON,
        remote_id="12345",
        handle="mariatta@fosstodon.org",
        instance_url=API,
        access_token="token-abc",
        metadata={"max_chars": 500, "max_asset_bytes": 2_000_000},
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """Media polling sleeps between attempts; tests should not."""
    monkeypatch.setattr(
        "content_planner.connectors.mastodon.time.sleep", lambda s: None
    )


def mock_registration():
    responses.post(
        f"{API}/api/v1/apps",
        json={"client_id": "cid", "client_secret": "csecret"},
    )


# ------------------------------------------------------------- app registry


@responses.activate
def test_register_app_stores_the_registration(db):
    mock_registration()
    app = register_app(HOST)
    assert app.client_id == "cid"
    assert MastodonApp.objects.count() == 1


@responses.activate
def test_register_app_reuses_an_existing_registration(db):
    mock_registration()
    first = register_app(HOST)
    second = register_app(HOST)
    assert first.pk == second.pk
    assert len(responses.calls) == 1  # no second round trip


@responses.activate
def test_client_secret_is_encrypted_at_rest(db):
    mock_registration()
    register_app(HOST)
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT client_secret FROM content_planner_mastodonapp")
        assert cursor.fetchone()[0] != "csecret"


# ---------------------------------------------------------------- instance


@responses.activate
def test_read_instance_limits_prefers_what_the_instance_reports(db):
    responses.get(
        f"{API}/api/v1/instance",
        json={
            "configuration": {
                "statuses": {"max_characters": 11000},
                "media_attachments": {
                    "image_size_limit": 16_777_216,
                    "supported_mime_types": ["image/jpeg"],
                },
            }
        },
    )
    assert read_instance_limits(HOST) == {
        "max_chars": 11000,
        "max_asset_bytes": 16_777_216,
        "supported_mimes": ["image/jpeg"],
    }


@responses.activate
def test_read_instance_limits_falls_back_when_absent(db):
    responses.get(f"{API}/api/v1/instance", json={})
    limits = read_instance_limits(HOST)
    assert limits["max_chars"] == FALLBACK_MAX_CHARS
    assert "supported_mimes" not in limits


def test_limits_use_cached_instance_facts(account):
    limits = MastodonConnector().limits(account)
    assert limits.max_chars == 500
    assert limits.max_asset_bytes == 2_000_000
    assert limits.requires_asset is False
    assert "image/jpeg" in limits.allowed_mimes


def test_limits_fall_back_without_metadata(account):
    account.metadata = {}
    limits = MastodonConnector().limits(account)
    assert limits.max_chars == FALLBACK_MAX_CHARS


# -------------------------------------------------------------------- auth


@responses.activate
def test_authorize_url_includes_state_and_scopes(db):
    mock_registration()
    url = MastodonConnector().authorize_url("st4te", host=HOST)
    assert url.startswith(f"{API}/oauth/authorize?")
    assert "client_id=cid" in url
    assert "state=st4te" in url
    assert "write%3Astatuses" in url or "write:statuses" in url


@responses.activate
def test_exchange_stores_the_account_and_instance_limits(user):
    mock_registration()
    responses.post(f"{API}/oauth/token", json={"access_token": "tok-1"})
    responses.get(
        f"{API}/api/v1/accounts/verify_credentials",
        json={"id": 999, "acct": "mariatta"},
    )
    responses.get(
        f"{API}/api/v1/instance",
        json={"configuration": {"statuses": {"max_characters": 500}}},
    )
    account = MastodonConnector().exchange("code", "state", host=HOST, owner=user)
    assert account.remote_id == "999"
    assert account.handle == "mariatta"
    assert account.access_token == "tok-1"
    assert account.expires_at is None  # Mastodon tokens do not expire
    assert account.status == PublishingAccount.Status.ACTIVE
    assert account.metadata["max_chars"] == 500
    assert account.last_verified_at is not None


@responses.activate
def test_exchange_is_idempotent_for_the_same_remote_account(user):
    mock_registration()
    responses.post(f"{API}/oauth/token", json={"access_token": "tok-2"})
    responses.get(
        f"{API}/api/v1/accounts/verify_credentials",
        json={"id": 999, "acct": "mariatta"},
    )
    responses.get(f"{API}/api/v1/instance", json={})
    connector = MastodonConnector()
    connector.exchange("c", "s", host=HOST, owner=user)
    connector.exchange("c", "s", host=HOST, owner=user)
    assert PublishingAccount.objects.count() == 1


@responses.activate
def test_refresh_reverifies_and_stamps_the_account(account):
    responses.get(f"{API}/api/v1/accounts/verify_credentials", json={"id": 1})
    before = account.last_verified_at
    MastodonConnector().refresh(account)
    account.refresh_from_db()
    assert account.last_verified_at != before


@responses.activate
def test_refresh_raises_when_the_token_was_revoked(account):
    responses.get(
        f"{API}/api/v1/accounts/verify_credentials",
        json={"error": "The access token is invalid"},
        status=401,
    )
    with pytest.raises(PermanentPublishError) as exc:
        MastodonConnector().refresh(account)
    assert exc.value.status_code == 401


# ----------------------------------------------------------------- publish


@responses.activate
def test_publish_sends_the_idempotency_key(account):
    responses.post(
        f"{API}/api/v1/statuses",
        json={"id": "110", "url": f"{API}/@mariatta/110"},
    )
    result = MastodonConnector().publish(
        account, PublishPayload(text="Hello"), "key-123"
    )
    assert result.remote_id == "110"
    assert result.remote_url == f"{API}/@mariatta/110"
    assert responses.calls[0].request.headers["Idempotency-Key"] == "key-123"


@responses.activate
def test_publish_uploads_media_and_attaches_it(account, no_sleep):
    responses.get("https://cdn.test/hero.jpg", body=b"jpegbytes")
    responses.post(f"{API}/api/v2/media", json={"id": "m1", "url": "https://x/1"})
    responses.post(f"{API}/api/v1/statuses", json={"id": "111", "url": "u"})
    payload = PublishPayload(
        text="With image",
        assets=[
            AssetRef(url="https://cdn.test/hero.jpg", mime="image/jpeg", alt="Alt")
        ],
    )
    MastodonConnector().publish(account, payload, "key-1")
    upload = responses.calls[1].request
    assert b"Alt" in upload.body
    assert b"media_ids%5B%5D=m1" in responses.calls[2].request.body.encode()


@responses.activate
def test_publish_waits_for_media_to_finish_processing(account, no_sleep):
    """202 means still converting: attaching it now would post a broken status."""
    responses.get("https://cdn.test/hero.jpg", body=b"jpegbytes")
    responses.post(f"{API}/api/v2/media", json={"id": "m2", "url": None}, status=202)
    responses.get(f"{API}/api/v1/media/m2", json={"id": "m2", "url": None})
    responses.get(f"{API}/api/v1/media/m2", json={"id": "m2", "url": "https://x/2"})
    responses.post(f"{API}/api/v1/statuses", json={"id": "112", "url": "u"})
    payload = PublishPayload(
        text="Slow media",
        assets=[AssetRef(url="https://cdn.test/hero.jpg", mime="image/jpeg", alt="A")],
    )
    MastodonConnector().publish(account, payload, "key-2")
    assert responses.calls[-1].request.url == f"{API}/api/v1/statuses"


@responses.activate
def test_publish_gives_up_on_media_stuck_processing(account, no_sleep):
    responses.get("https://cdn.test/hero.jpg", body=b"jpegbytes")
    responses.post(f"{API}/api/v2/media", json={"id": "m3", "url": None}, status=202)
    for _ in range(MEDIA_POLL_ATTEMPTS):
        responses.get(f"{API}/api/v1/media/m3", json={"id": "m3", "url": None})
    payload = PublishPayload(
        text="Stuck",
        assets=[AssetRef(url="https://cdn.test/hero.jpg", mime="image/jpeg", alt="A")],
    )
    with pytest.raises(PermanentPublishError, match="still processing"):
        MastodonConnector().publish(account, payload, "key-3")


@responses.activate
def test_publish_maps_rate_limiting_to_a_retry(account):
    responses.post(f"{API}/api/v1/statuses", json={"error": "Slow down"}, status=429)
    with pytest.raises(TransientPublishError) as exc:
        MastodonConnector().publish(account, PublishPayload(text="x"), "k")
    assert exc.value.status_code == 429


@responses.activate
def test_publish_maps_validation_failure_to_permanent(account):
    responses.post(
        f"{API}/api/v1/statuses", json={"error": "Text too long"}, status=422
    )
    with pytest.raises(PermanentPublishError, match="Text too long"):
        MastodonConnector().publish(account, PublishPayload(text="x" * 9999), "k")


def test_publish_without_an_instance_url_fails_clearly(account):
    account.instance_url = ""
    with pytest.raises(PermanentPublishError, match="no instance URL"):
        MastodonConnector().publish(account, PublishPayload(text="x"), "k")


# --------------------------------------------------------------- transport


@responses.activate
def test_transport_treats_network_errors_as_transient(db):
    responses.get(
        f"{API}/api/v1/instance", body=requests.exceptions.ConnectionError("boom")
    )
    with pytest.raises(TransientPublishError, match="failed"):
        transport.request("GET", f"{API}/api/v1/instance")


@responses.activate
def test_transport_reports_non_json_errors(db):
    responses.get(f"{API}/x", body="<html>gateway</html>", status=500)
    with pytest.raises(TransientPublishError, match="gateway"):
        transport.request("GET", f"{API}/x")


@responses.activate
def test_transport_reports_list_shaped_errors(db):
    responses.get(f"{API}/x", json=["nope"], status=400)
    with pytest.raises(PermanentPublishError, match="nope"):
        transport.request("GET", f"{API}/x")


@responses.activate
def test_fetch_bytes_returns_content(db):
    responses.get("https://cdn.test/a.jpg", body=b"abc")
    assert transport.fetch_bytes("https://cdn.test/a.jpg") == b"abc"


# ------------------------------------------------------------ connect flow


def test_accounts_page_lists_accounts(auth_client, account):
    response = auth_client.get(reverse("content_planner:publishing_accounts"))
    assert response.status_code == 200
    assert b"mariatta@fosstodon.org" in response.content
    assert b"token-abc" not in response.content  # invariant: tokens never render


def test_accounts_page_empty_state(auth_client):
    response = auth_client.get(reverse("content_planner:publishing_accounts"))
    assert b"No accounts connected yet" in response.content


def test_accounts_page_requires_the_app_permission(client, db):
    User.objects.create_user(username="plain", password="pw")
    client.login(username="plain", password="pw")
    response = client.get(reverse("content_planner:publishing_accounts"))
    assert response.status_code == 302


@responses.activate
def test_connect_redirects_to_the_instance(auth_client):
    mock_registration()
    response = auth_client.post(
        reverse("content_planner:mastodon_connect"), {"instance": "@me@fosstodon.org"}
    )
    assert response.status_code == 302
    assert response["Location"].startswith(f"{API}/oauth/authorize")
    assert auth_client.session["mastodon_oauth_host"] == HOST


def test_connect_without_an_instance_says_so(auth_client):
    response = auth_client.post(reverse("content_planner:mastodon_connect"), {})
    assert response["Location"] == reverse("content_planner:publishing_accounts")


@responses.activate
def test_connect_surfaces_an_unreachable_instance(auth_client):
    responses.post(f"{API}/api/v1/apps", json={"error": "nope"}, status=404)
    response = auth_client.post(
        reverse("content_planner:mastodon_connect"), {"instance": HOST}
    )
    assert response["Location"] == reverse("content_planner:publishing_accounts")
    assert PublishingAccount.objects.count() == 0


@responses.activate
def test_callback_connects_the_account(auth_client, user):
    mock_registration()
    responses.post(f"{API}/oauth/token", json={"access_token": "tok"})
    responses.get(
        f"{API}/api/v1/accounts/verify_credentials", json={"id": 7, "acct": "m"}
    )
    responses.get(f"{API}/api/v1/instance", json={})
    auth_client.post(reverse("content_planner:mastodon_connect"), {"instance": HOST})
    state = auth_client.session["mastodon_oauth_state"]
    response = auth_client.get(
        reverse("content_planner:mastodon_callback"), {"code": "c", "state": state}
    )
    assert response["Location"] == reverse("content_planner:publishing_accounts")
    assert PublishingAccount.objects.get(owner=user).handle == "m"


def test_callback_rejects_a_mismatched_state(auth_client):
    response = auth_client.get(
        reverse("content_planner:mastodon_callback"), {"code": "c", "state": "wrong"}
    )
    assert response.status_code == 400


@responses.activate
def test_callback_requires_a_code(auth_client):
    mock_registration()
    auth_client.post(reverse("content_planner:mastodon_connect"), {"instance": HOST})
    state = auth_client.session["mastodon_oauth_state"]
    response = auth_client.get(
        reverse("content_planner:mastodon_callback"), {"state": state}
    )
    assert response.status_code == 400


@responses.activate
def test_callback_surfaces_a_rejected_exchange(auth_client):
    mock_registration()
    responses.post(f"{API}/oauth/token", json={"error": "bad code"}, status=400)
    auth_client.post(reverse("content_planner:mastodon_connect"), {"instance": HOST})
    state = auth_client.session["mastodon_oauth_state"]
    response = auth_client.get(
        reverse("content_planner:mastodon_callback"), {"code": "c", "state": state}
    )
    assert response["Location"] == reverse("content_planner:publishing_accounts")
    assert PublishingAccount.objects.count() == 0


def test_disconnect_deletes_an_unused_account(auth_client, account):
    response = auth_client.post(
        reverse(
            "content_planner:publishing_account_disconnect", kwargs={"pk": account.pk}
        )
    )
    assert response.status_code == 302
    assert PublishingAccount.objects.count() == 0


def test_disconnect_keeps_an_account_with_history(auth_client, account, user):
    """PROTECT means history wins: revoke rather than delete."""
    from django.utils import timezone

    from content_planner.models import Campaign, ContentBoard, Post, Publication

    board = ContentBoard.objects.create(name="B", slug="b", owner=user)
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="P", channel="mastodon")
    Publication.objects.create(post=post, account=account, scheduled_for=timezone.now())
    auth_client.post(
        reverse(
            "content_planner:publishing_account_disconnect", kwargs={"pk": account.pk}
        )
    )
    account.refresh_from_db()
    assert account.status == PublishingAccount.Status.REVOKED
    assert account.access_token == ""


def test_disconnect_is_scoped_to_the_owner(client, account, db):
    stranger = User.objects.create_user(username="stranger", password="pw")
    stranger.user_permissions.add(
        Permission.objects.get(
            codename="access_content_planner",
            content_type__app_label="content_planner",
        )
    )
    client.force_login(stranger)
    response = client.post(
        reverse(
            "content_planner:publishing_account_disconnect", kwargs={"pk": account.pk}
        )
    )
    assert response.status_code == 404
