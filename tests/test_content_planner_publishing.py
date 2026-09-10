"""Social publishing M1: models, preflight, connectors, dispatcher, retries.

No real platform is involved: `FakeConnector` records what would have been
sent, which is what makes the delivery machinery testable before any API
credentials exist.
"""

import datetime
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.utils import timezone

from content_planner import tasks
from content_planner.connectors import (
    PermanentPublishError,
    PlatformLimits,
    TransientPublishError,
    connector_for,
)
from content_planner.connectors.fake import DEFAULT_LIMITS, FakeConnector
from content_planner.models import (
    Asset,
    Campaign,
    ContentBoard,
    MastodonApp,
    Platform,
    Post,
    Publication,
    PublishingAccount,
)
from content_planner.payloads import absolute_url, build_payload, mime_for
from content_planner.preflight import Blocker, grapheme_len, preflight

User = get_user_model()

FAKE_PATH = "content_planner.connectors.fake.FakeConnector"


@pytest.fixture(autouse=True)
def media_root(tmp_path, settings):
    """Asset uploads land in a temp dir: /code/media is not writable in CI."""
    settings.MEDIA_ROOT = str(tmp_path)
    return settings.MEDIA_ROOT


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner")


@pytest.fixture
def board(owner):
    return ContentBoard.objects.create(name="Board", slug="board", owner=owner)


@pytest.fixture
def campaign(board):
    return Campaign.objects.create(board=board, name="Series")


@pytest.fixture
def post(campaign):
    return Post.objects.create(
        campaign=campaign,
        title="Announce",
        channel="bluesky",
        body_snippet="Hello world",
        status=Post.Status.SCHEDULED,
    )


@pytest.fixture
def account(owner):
    return PublishingAccount.objects.create(
        owner=owner,
        platform=Platform.BLUESKY,
        remote_id="did:plc:abc123",
        handle="mariatta.bsky.social",
        access_token="app-password",
    )


@pytest.fixture
def publication(post, account):
    return Publication.objects.create(
        post=post, account=account, scheduled_for=timezone.now()
    )


@pytest.fixture
def use_fake(settings):
    """Route every platform at the fake connector."""
    settings.CONTENT_PLANNER_CONNECTORS = {p.value: FAKE_PATH for p in Platform}
    return settings


def image(name="hero.jpg", board=None, caption="A hero image", content=b"x"):
    return Asset.objects.create(
        board=board,
        name=name,
        caption=caption,
        file=SimpleUploadedFile(name, content, content_type="image/jpeg"),
    )


# ------------------------------------------------------------------- models


def test_social_account_str_hides_credentials(account):
    rendered = str(account)
    assert rendered == "mariatta.bsky.social (Bluesky)"
    assert "app-password" not in rendered


def raw_column(table, column, pk):
    """Read a column straight from Postgres, bypassing field decryption."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


def test_access_token_is_encrypted_at_rest(account):
    """The column holds ciphertext; the attribute round-trips to plaintext."""
    stored = raw_column("content_planner_publishingaccount", "access_token", account.pk)
    assert stored != "app-password"
    assert PublishingAccount.objects.get(pk=account.pk).access_token == "app-password"


def test_duplicate_account_rejected(owner, account):
    with pytest.raises(IntegrityError):
        PublishingAccount.objects.create(
            owner=owner,
            platform=Platform.BLUESKY,
            remote_id=account.remote_id,
            handle="renamed.bsky.social",
        )


def test_mastodon_app_str_and_secret_encrypted(db):
    app = MastodonApp.objects.create(
        instance_host="fosstodon.org", client_id="cid", client_secret="shhh"
    )
    assert str(app) == "fosstodon.org"
    assert raw_column("content_planner_mastodonapp", "client_secret", app.pk) != "shhh"


def test_publication_str_and_blocker_messages(publication):
    assert str(publication) == "Announce → mariatta.bsky.social"
    publication.blockers = [{"code": "alt_text", "message": "no alt text"}]
    assert publication.blocker_messages == ["no alt text"]


def test_one_success_per_target_enforced_by_database(publication, post, account):
    """Invariant §2.2: the duplicate guard is a constraint, not a code path."""
    publication.state = Publication.State.SENT
    publication.save()
    with pytest.raises(IntegrityError):
        Publication.objects.create(
            post=post,
            account=account,
            scheduled_for=timezone.now(),
            state=Publication.State.SENT,
        )


def test_failed_retry_row_is_allowed_alongside_a_sent_one(publication, post, account):
    """The constraint is partial: only `sent` rows collide."""
    publication.state = Publication.State.SENT
    publication.save()
    other = Publication.objects.create(
        post=post,
        account=account,
        scheduled_for=timezone.now(),
        state=Publication.State.FAILED,
    )
    assert other.pk


def test_idempotency_keys_are_unique(publication, post, account):
    second = Publication.objects.create(
        post=post, account=account, scheduled_for=timezone.now()
    )
    assert isinstance(publication.idempotency_key, uuid.UUID)
    assert publication.idempotency_key != second.idempotency_key


# --------------------------------------------------------------- connectors


def test_connector_for_unmapped_platform_fails_loudly(account, settings):
    settings.CONTENT_PLANNER_CONNECTORS = {}
    with pytest.raises(PermanentPublishError, match="No connector"):
        connector_for(account)


def test_connector_for_returns_configured_connector(account, use_fake):
    assert isinstance(connector_for(account), FakeConnector)


def test_fake_connector_surface(account):
    connector = FakeConnector()
    assert connector.limits(account) is DEFAULT_LIMITS
    assert connector.refresh(account) is None
    assert "state=xyz" in connector.authorize_url("xyz")
    with pytest.raises(PermanentPublishError):
        connector.exchange("code", "state")


# ---------------------------------------------------------------- preflight


def test_preflight_passes_a_healthy_publication(publication):
    assert preflight(publication, DEFAULT_LIMITS) == []


def test_preflight_is_deterministic(publication):
    """Invariant §2.3: same input, same answer, no writes in between."""
    runs = [preflight(publication, DEFAULT_LIMITS) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_preflight_blocks_unscheduled_post(publication):
    publication.post.status = Post.Status.DRAFTING
    publication.post.save()
    codes = [b.code for b in preflight(publication, DEFAULT_LIMITS)]
    assert codes == ["not_scheduled"]


def test_preflight_blocks_account_needing_reauth(publication):
    publication.account.status = PublishingAccount.Status.NEEDS_REAUTH
    publication.account.save()
    blockers = preflight(publication, DEFAULT_LIMITS)
    assert [b.code for b in blockers] == ["account"]
    assert "mariatta.bsky.social" in blockers[0].message


def test_preflight_blocks_token_expiring_before_send(publication):
    publication.account.expires_at = publication.scheduled_for - datetime.timedelta(
        hours=1
    )
    publication.account.save()
    assert [b.code for b in preflight(publication, DEFAULT_LIMITS)] == ["token_expiry"]


def test_preflight_requires_asset_when_platform_does(publication):
    limits = DEFAULT_LIMITS._replace(requires_asset=True)
    assert [b.code for b in preflight(publication, limits)] == ["no_asset"]


def test_preflight_blocks_too_many_assets(publication, board):
    for i in range(3):
        publication.post.assets.add(image(name=f"a{i}.jpg", board=board))
    limits = DEFAULT_LIMITS._replace(max_assets=2)
    assert "too_many_assets" in [b.code for b in preflight(publication, limits)]


def test_preflight_requires_alt_text(publication, board):
    publication.post.assets.add(image(board=board, caption=""))
    blockers = preflight(publication, DEFAULT_LIMITS)
    assert [b.code for b in blockers] == ["alt_text"]
    assert "hero.jpg" in blockers[0].message


def test_preflight_blocks_asset_without_a_file(publication, board):
    asset = Asset.objects.create(board=board, name="ghost.jpg", caption="Alt")
    publication.post.assets.add(asset)
    assert [b.code for b in preflight(publication, DEFAULT_LIMITS)] == ["missing_file"]


def test_preflight_blocks_disallowed_mime(publication, board):
    publication.post.assets.add(image(name="clip.mp4", board=board))
    blockers = preflight(publication, DEFAULT_LIMITS)
    assert [b.code for b in blockers] == ["mime"]
    assert "video/mp4" in blockers[0].message


def test_preflight_blocks_oversized_asset(publication, board):
    publication.post.assets.add(image(board=board, content=b"x" * 2048))
    limits = DEFAULT_LIMITS._replace(max_asset_bytes=1024)
    assert [b.code for b in preflight(publication, limits)] == ["asset_too_large"]


def test_preflight_blocks_overlong_text(publication):
    publication.post.body_snippet = "a" * 400
    publication.post.save()
    blockers = preflight(publication, DEFAULT_LIMITS)
    assert [b.code for b in blockers] == ["too_long"]
    assert "400/300" in blockers[0].message


def test_preflight_counts_graphemes_not_code_points(publication):
    """A family emoji is one character to a platform, five code points to len()."""
    publication.post.body_snippet = "👩‍👩‍👧‍👦" * 20
    publication.post.save()
    limits = DEFAULT_LIMITS._replace(max_chars=25)
    assert preflight(publication, limits) == []
    assert grapheme_len("👩‍👩‍👧‍👦") == 1


def test_preflight_blocks_too_many_hashtags(publication):
    publication.post.hashtags = "#a #b #c"
    publication.post.save()
    limits = DEFAULT_LIMITS._replace(max_hashtags=2)
    assert [b.code for b in preflight(publication, limits)] == ["hashtags"]


def test_blocker_as_dict():
    assert Blocker("mime", "bad type").as_dict() == {
        "code": "mime",
        "message": "bad type",
    }


# ----------------------------------------------------------------- payloads


def test_build_payload_renders_text_and_assets(publication, board):
    publication.post.hashtags = "#python"
    publication.post.save()
    publication.post.assets.add(image(board=board))
    payload = build_payload(publication)
    assert payload.text == "Hello world\n\n#python"
    assert [a.mime for a in payload.assets] == ["image/jpeg"]
    assert payload.assets[0].alt == "A hero image"
    assert payload.assets[0].byte_size == 1


def test_asset_urls_are_made_absolute_for_connectors(publication, board, settings):
    """A connector fetches over HTTP; "/media/…" is not fetchable."""
    settings.DOMAIN_NAME = "https://secretcodes.dev"
    publication.post.assets.add(image(board=board))
    assert (
        build_payload(publication)
        .assets[0]
        .url.startswith("https://secretcodes.dev/media/")
    )


def test_absolute_url_leaves_remote_storage_alone():
    assert absolute_url("https://spaces.test/a.jpg") == "https://spaces.test/a.jpg"


def test_build_payload_carries_published_link(publication):
    publication.post.published_url = "https://example.test/post"
    publication.post.save()
    assert build_payload(publication).link == "https://example.test/post"


def test_mime_for_known_and_unknown_extensions(board):
    assert mime_for(image(name="card.avif", board=board)) == "image/avif"
    assert mime_for(Asset.objects.create(board=board, name="none")) == ""


# --------------------------------------------------------------- dispatcher


@pytest.fixture
def collected(monkeypatch):
    """Capture publish_one.delay calls instead of running them."""
    sent = []
    monkeypatch.setattr(tasks.publish_one, "delay", sent.append)
    return sent


def test_dispatcher_claims_due_publications(publication, collected):
    assert tasks.dispatch_due_publications() == 1
    publication.refresh_from_db()
    assert publication.state == Publication.State.CLAIMED
    assert publication.claimed_at is not None
    assert collected == [publication.pk]


def test_dispatcher_ignores_future_publications(publication, collected):
    publication.scheduled_for = timezone.now() + datetime.timedelta(hours=1)
    publication.save()
    assert tasks.dispatch_due_publications() == 0
    assert collected == []


def test_dispatcher_respects_retry_backoff(publication, collected):
    publication.next_attempt_at = timezone.now() + datetime.timedelta(minutes=10)
    publication.save()
    assert tasks.dispatch_due_publications() == 0


def test_dispatcher_claims_each_row_once(post, account, collected):
    """The whole campaign dispatches, and a second tick finds nothing left."""
    for i in range(78):
        p = Post.objects.create(
            campaign=post.campaign,
            title=f"Post {i}",
            channel="bluesky",
            status=Post.Status.SCHEDULED,
        )
        Publication.objects.create(
            post=p, account=account, scheduled_for=timezone.now()
        )
    assert tasks.dispatch_due_publications() == tasks.CLAIM_BATCH_SIZE
    assert tasks.dispatch_due_publications() == 28
    assert tasks.dispatch_due_publications() == 0
    assert len(collected) == len(set(collected)) == 78


def test_reaper_returns_stranded_claims(publication, settings):
    """A worker died mid-flight, before any call went out."""
    publication.state = Publication.State.CLAIMED
    publication.claimed_at = timezone.now() - datetime.timedelta(minutes=30)
    publication.save()
    assert tasks.reap_stale_claims() == 1
    publication.refresh_from_db()
    assert publication.state == Publication.State.PENDING
    assert publication.claimed_at is None


def test_reaper_leaves_claims_that_may_have_landed(publication):
    """A remote_id means the call succeeded; re-running it would double-post."""
    publication.state = Publication.State.CLAIMED
    publication.claimed_at = timezone.now() - datetime.timedelta(minutes=30)
    publication.remote_id = "at://did:plc:abc123/app.bsky.feed.post/1"
    publication.save()
    assert tasks.reap_stale_claims() == 0
    publication.refresh_from_db()
    assert publication.state == Publication.State.CLAIMED


def test_reaper_leaves_fresh_claims(publication):
    publication.state = Publication.State.CLAIMED
    publication.claimed_at = timezone.now()
    publication.save()
    assert tasks.reap_stale_claims() == 0


# ------------------------------------------------------------- publish_one


def claim(publication):
    """Put the row in the state the dispatcher would have left it in."""
    publication.refresh_from_db()
    publication.state = Publication.State.CLAIMED
    publication.claimed_at = timezone.now()
    publication.save()
    return publication


def test_publish_one_sends_and_records_the_result(publication, use_fake, monkeypatch):
    recorder = FakeConnector()
    monkeypatch.setattr("content_planner.tasks.connector_for", lambda account: recorder)
    assert tasks.publish_one(claim(publication).pk) == Publication.State.SENT
    publication.refresh_from_db()
    assert publication.remote_id == "fake-1"
    assert publication.remote_url.endswith("/1")
    assert publication.sent_at is not None
    assert publication.attempts == 1
    account_pk, payload, key = recorder.calls[0]
    assert payload.text == "Hello world"
    assert key == str(publication.idempotency_key)


def test_publish_one_skips_rows_it_does_not_own(publication, use_fake):
    """Cancelled between claim and execution: leave it alone."""
    publication.state = Publication.State.CANCELLED
    publication.save()
    assert tasks.publish_one(publication.pk) == Publication.State.CANCELLED


def test_publish_one_blocks_instead_of_sending(publication, use_fake, monkeypatch):
    recorder = FakeConnector()
    monkeypatch.setattr("content_planner.tasks.connector_for", lambda account: recorder)
    publication.post.status = Post.Status.DRAFTING
    publication.post.save()
    assert tasks.publish_one(claim(publication).pk) == Publication.State.BLOCKED
    publication.refresh_from_db()
    assert publication.blocker_messages == ["Post is drafting, not scheduled."]
    assert recorder.calls == []


def test_publish_one_fails_without_a_connector(publication, settings):
    settings.CONTENT_PLANNER_CONNECTORS = {}
    assert tasks.publish_one(claim(publication).pk) == Publication.State.FAILED
    publication.refresh_from_db()
    assert "No connector" in publication.last_error


def test_publish_one_flags_the_account_when_the_token_is_rejected(
    publication, monkeypatch
):
    """A 401 is the credential's problem, not the post's: stop and ask."""
    monkeypatch.setattr(
        "content_planner.tasks.connector_for",
        lambda account: FakeConnector(
            raises=PermanentPublishError("revoked", status_code=401)
        ),
    )
    assert tasks.publish_one(claim(publication).pk) == Publication.State.FAILED
    publication.account.refresh_from_db()
    assert publication.account.status == PublishingAccount.Status.NEEDS_REAUTH


def test_publish_one_leaves_the_account_alone_on_a_content_rejection(
    publication, monkeypatch
):
    monkeypatch.setattr(
        "content_planner.tasks.connector_for",
        lambda account: FakeConnector(
            raises=PermanentPublishError("too long", status_code=422)
        ),
    )
    tasks.publish_one(claim(publication).pk)
    publication.account.refresh_from_db()
    assert publication.account.status == PublishingAccount.Status.ACTIVE


def test_publish_one_does_not_retry_permanent_errors(publication, monkeypatch):
    monkeypatch.setattr(
        "content_planner.tasks.connector_for",
        lambda account: FakeConnector(raises=PermanentPublishError("rejected")),
    )
    assert tasks.publish_one(claim(publication).pk) == Publication.State.FAILED
    publication.refresh_from_db()
    assert publication.attempts == 1
    assert publication.next_attempt_at is None


def test_publish_one_backs_off_after_a_transient_error(publication, monkeypatch):
    monkeypatch.setattr(
        "content_planner.tasks.connector_for",
        lambda account: FakeConnector(raises=TransientPublishError("503")),
    )
    assert tasks.publish_one(claim(publication).pk) == Publication.State.PENDING
    publication.refresh_from_db()
    assert publication.attempts == 1
    assert publication.claimed_at is None
    delay = publication.next_attempt_at - timezone.now()
    assert datetime.timedelta(minutes=1) < delay <= datetime.timedelta(minutes=2)


def test_publish_one_gives_up_after_the_backoff_schedule(publication, monkeypatch):
    monkeypatch.setattr(
        "content_planner.tasks.connector_for",
        lambda account: FakeConnector(raises=TransientPublishError("503")),
    )
    for _ in tasks.RETRY_BACKOFF:
        assert tasks.publish_one(claim(publication).pk) == Publication.State.PENDING
    assert tasks.publish_one(claim(publication).pk) == Publication.State.FAILED
    publication.refresh_from_db()
    assert publication.attempts == len(tasks.RETRY_BACKOFF) + 1
    assert publication.last_error == "503"


def test_a_survived_retry_cannot_double_post(publication, monkeypatch):
    """The claim/send cycle run twice yields one `sent` row, not two."""
    monkeypatch.setattr(
        "content_planner.tasks.connector_for", lambda account: FakeConnector()
    )
    tasks.publish_one(claim(publication).pk)
    assert tasks.publish_one(publication.pk) == Publication.State.SENT
    assert (
        Publication.objects.filter(
            post=publication.post,
            account=publication.account,
            state=Publication.State.SENT,
        ).count()
        == 1
    )


# ----------------------------------------------------------------- logging


def test_publishing_never_logs_a_token(publication, monkeypatch, caplog):
    """Invariant §2.6: credentials do not reach the log stream."""
    monkeypatch.setattr(
        "content_planner.tasks.connector_for", lambda account: FakeConnector()
    )
    with caplog.at_level("DEBUG"):
        tasks.publish_one(claim(publication).pk)
    assert caplog.records
    assert not any("app-password" in r.getMessage() for r in caplog.records)


def test_limits_are_a_value_object():
    limits = PlatformLimits(
        max_chars=500,
        max_hashtags=30,
        max_assets=4,
        requires_asset=True,
        allowed_mimes=frozenset({"image/jpeg"}),
        max_asset_bytes=8_000_000,
    )
    assert limits._replace(max_chars=300).max_chars == 300
