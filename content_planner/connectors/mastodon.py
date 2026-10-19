"""Mastodon connector.

The simplest real platform, and the only one of the three with server-side
idempotency: ``Idempotency-Key`` means a retry after a timeout that actually
succeeded returns the original status instead of posting twice.

Everything here is per-instance. Character limits, accepted MIME types, and
the client registration itself all differ between servers, so they are read
from the instance and cached on the account rather than hard-coded.
"""

import time

from django.conf import settings
from django.utils import timezone

from ..models import MastodonApp, Platform, PublishingAccount
from .base import PermanentPublishError, PlatformLimits, PublishResult
from .transport import fetch_bytes, request

CLIENT_NAME = "Secret Codes content planner"
SCOPES = "read:accounts write:statuses write:media"

# Used until the instance tells us otherwise (Mastodon's own defaults).
FALLBACK_MAX_CHARS = 500
FALLBACK_MAX_ASSET_BYTES = 10 * 1024 * 1024
FALLBACK_MIMES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}
)
MAX_ASSETS = 4

# Media is processed asynchronously; a status must not reference an
# attachment that is still converting.
MEDIA_POLL_INTERVAL = 1
MEDIA_POLL_ATTEMPTS = 30


def _api(host, path):
    return f"https://{host}{path}"


def _auth(account):
    return {"Authorization": f"Bearer {account.access_token}"}


def register_app(host):
    """Register this app with one instance, or reuse the stored registration."""
    existing = MastodonApp.objects.filter(instance_host=host).first()
    if existing:
        return existing
    response = request(
        "POST",
        _api(host, "/api/v1/apps"),
        data={
            "client_name": CLIENT_NAME,
            "redirect_uris": settings.MASTODON_REDIRECT_URI,
            "scopes": SCOPES,
            "website": settings.DOMAIN_NAME,
        },
    )
    payload = response.json()
    return MastodonApp.objects.create(
        instance_host=host,
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
    )


class MastodonConnector:
    platform = Platform.MASTODON

    def limits(self, account):
        """Instance limits, read at connect time and cached on the account."""
        metadata = account.metadata or {}
        mimes = metadata.get("supported_mimes")
        return PlatformLimits(
            max_chars=metadata.get("max_chars", FALLBACK_MAX_CHARS),
            max_hashtags=None,
            max_assets=MAX_ASSETS,
            requires_asset=False,
            allowed_mimes=frozenset(mimes) if mimes else FALLBACK_MIMES,
            max_asset_bytes=metadata.get("max_asset_bytes", FALLBACK_MAX_ASSET_BYTES),
        )

    def authorize_url(self, state, *, host):
        app = register_app(host)
        query = "&".join(
            [
                f"client_id={app.client_id}",
                f"redirect_uri={settings.MASTODON_REDIRECT_URI}",
                "response_type=code",
                f"scope={SCOPES.replace(' ', '+')}",
                f"state={state}",
            ]
        )
        return _api(host, f"/oauth/authorize?{query}")

    def exchange(self, code, state, *, host, owner):
        """Trade the callback code for a token and store the account."""
        app = register_app(host)
        token = request(
            "POST",
            _api(host, "/oauth/token"),
            data={
                "grant_type": "authorization_code",
                "client_id": app.client_id,
                "client_secret": app.client_secret,
                "redirect_uri": settings.MASTODON_REDIRECT_URI,
                "code": code,
                "scope": SCOPES,
            },
        ).json()
        access_token = token["access_token"]

        who = request(
            "GET",
            _api(host, "/api/v1/accounts/verify_credentials"),
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()

        account, _ = PublishingAccount.objects.update_or_create(
            owner=owner,
            platform=Platform.MASTODON,
            remote_id=str(who["id"]),
            defaults={
                "handle": who["acct"],
                "instance_url": f"https://{host}",
                "access_token": access_token,
                # Mastodon tokens do not expire; they are revoked instead.
                "expires_at": None,
                "scopes": SCOPES.split(),
                "status": PublishingAccount.Status.ACTIVE,
                "last_verified_at": timezone.now(),
                "metadata": read_instance_limits(host),
            },
        )
        return account

    def refresh(self, account):
        """No refresh flow: Mastodon tokens live until revoked.

        Re-verifying is how a revoked token surfaces, so that is what this
        does; a 401 raises and the caller flags the account.
        """
        request(
            "GET",
            _api(self._host(account), "/api/v1/accounts/verify_credentials"),
            headers=_auth(account),
        )
        account.last_verified_at = timezone.now()
        account.save(update_fields=["last_verified_at"])

    def publish(self, account, payload, idempotency_key):
        host = self._host(account)
        media_ids = [self._upload(host, account, a) for a in payload.assets]
        data = [("status", payload.text), ("visibility", "public"), ("language", "en")]
        data += [("media_ids[]", media_id) for media_id in media_ids]
        status = request(
            "POST",
            _api(host, "/api/v1/statuses"),
            headers={**_auth(account), "Idempotency-Key": idempotency_key},
            data=data,
        ).json()
        return PublishResult(
            remote_id=str(status["id"]),
            remote_url=status.get("url", ""),
            raw=status,
        )

    def _upload(self, host, account, asset):
        """Upload one attachment and wait for the instance to finish with it."""
        response = request(
            "POST",
            _api(host, "/api/v2/media"),
            headers=_auth(account),
            files={"file": (asset.url.rsplit("/", 1)[-1], fetch_bytes(asset.url))},
            data={"description": asset.alt},
        )
        media = response.json()
        if response.status_code == 202:
            self._await_processing(host, account, media["id"])
        return media["id"]

    def _await_processing(self, host, account, media_id):
        """202 means "still converting" — poll until the URL exists."""
        for _ in range(MEDIA_POLL_ATTEMPTS):
            response = request(
                "GET",
                _api(host, f"/api/v1/media/{media_id}"),
                headers=_auth(account),
            )
            if response.status_code == 200 and response.json().get("url"):
                return
            time.sleep(MEDIA_POLL_INTERVAL)
        raise PermanentPublishError(
            f"Attachment {media_id} was still processing after "
            f"{MEDIA_POLL_ATTEMPTS * MEDIA_POLL_INTERVAL}s."
        )

    def _host(self, account):
        host = (account.instance_url or "").removeprefix("https://").strip("/")
        if not host:
            raise PermanentPublishError(
                f"{account.handle} has no instance URL to publish to."
            )
        return host


def read_instance_limits(host):
    """Cacheable facts about one instance, for `limits()` and preflight."""
    configuration = (
        request("GET", _api(host, "/api/v1/instance")).json().get("configuration", {})
    )
    statuses = configuration.get("statuses", {})
    media = configuration.get("media_attachments", {})
    limits = {
        "max_chars": statuses.get("max_characters", FALLBACK_MAX_CHARS),
        "max_asset_bytes": media.get("image_size_limit", FALLBACK_MAX_ASSET_BYTES),
    }
    supported = media.get("supported_mime_types")
    if supported:
        limits["supported_mimes"] = supported
    return limits
