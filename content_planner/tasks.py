"""Celery tasks for delivery.

The schedule lives in Postgres, never in the broker: beat only ticks, and each
tick claims whatever is due *now*. A task queued three weeks ahead would be
invisible to the queue screen, uneditable, and lost on a broker flush, so
retries are dated rows (``next_attempt_at``) rather than countdowns.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .connectors import PermanentPublishError, TransientPublishError, connector_for
from .models import Publication, PublishingAccount
from .payloads import build_payload
from .preflight import preflight

logger = logging.getLogger(__name__)

# §8.3: attempt 1 immediate, then +2m, +10m, +1h, +4h, then give up.
RETRY_BACKOFF = [
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=4),
]
CLAIM_BATCH_SIZE = 50
# Platform responses that mean "this credential is done", not "this post is bad".
REAUTH_STATUSES = frozenset({401, 403})


@shared_task(name="content_planner.dispatch_due_publications")
def dispatch_due_publications():
    """Claim every due publication and hand each to a worker.

    ``skip_locked`` keeps this safe with several beats or workers running: a
    row claimed by one dispatcher is invisible to the others.
    """
    now = timezone.now()
    with transaction.atomic():
        ids = list(
            Publication.objects.select_for_update(skip_locked=True)
            .filter(
                Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
                state=Publication.State.PENDING,
                scheduled_for__lte=now,
            )
            .order_by("scheduled_for")
            .values_list("id", flat=True)[:CLAIM_BATCH_SIZE]
        )
        Publication.objects.filter(id__in=ids).update(
            state=Publication.State.CLAIMED, claimed_at=now, modified_date=now
        )
    for publication_id in ids:
        publish_one.delay(publication_id)
    return len(ids)


@shared_task(name="content_planner.publish_one")
def publish_one(publication_id):
    """Deliver one claimed publication.

    Preflight runs again here: minutes may have passed since it was scheduled,
    and an asset can go missing or a token expire in between.
    """
    publication = Publication.objects.select_related(
        "account", "post__campaign__board"
    ).get(pk=publication_id)
    if publication.state != Publication.State.CLAIMED:
        # Cancelled, or already delivered by another worker.
        return publication.state

    try:
        connector = connector_for(publication.account)
        limits = connector.limits(publication.account)
    except PermanentPublishError as exc:
        return _fail(publication, exc)

    blockers = preflight(publication, limits)
    if blockers:
        return _block(publication, blockers)

    logger.info(
        "publishing %s to %s (idempotency_key=%s)",
        publication.pk,
        publication.account.platform,
        publication.idempotency_key,
    )
    try:
        result = connector.publish(
            publication.account,
            build_payload(publication),
            str(publication.idempotency_key),
        )
    except TransientPublishError as exc:
        return _retry_later(publication, exc)
    except PermanentPublishError as exc:
        return _fail(publication, exc)

    publication.state = Publication.State.SENT
    publication.remote_id = result.remote_id
    publication.remote_url = result.remote_url
    publication.sent_at = timezone.now()
    publication.attempts += 1
    publication.last_error = ""
    publication.blockers = []
    publication.save(
        update_fields=[
            "state",
            "remote_id",
            "remote_url",
            "sent_at",
            "attempts",
            "last_error",
            "blockers",
        ]
    )
    return publication.state


@shared_task(name="content_planner.reap_stale_claims")
def reap_stale_claims():
    """Return publications whose worker died mid-flight to ``pending``.

    Only rows with no ``remote_id``: if the call landed before the worker went
    away, retrying it would double-post.
    """
    cutoff = timezone.now() - timedelta(
        minutes=settings.PUBLICATION_CLAIM_TIMEOUT_MINUTES
    )
    return Publication.objects.filter(
        state=Publication.State.CLAIMED, claimed_at__lte=cutoff, remote_id=""
    ).update(
        state=Publication.State.PENDING, claimed_at=None, modified_date=timezone.now()
    )


def _block(publication, blockers):
    publication.state = Publication.State.BLOCKED
    publication.blockers = [b.as_dict() for b in blockers]
    publication.save(update_fields=["state", "blockers"])
    logger.info("publication %s blocked: %s", publication.pk, publication.blockers)
    return publication.state


def _fail(publication, exc):
    publication.state = Publication.State.FAILED
    publication.attempts += 1
    publication.last_error = str(exc)
    publication.save(update_fields=["state", "attempts", "last_error"])
    logger.warning("publication %s failed: %s", publication.pk, exc)
    if getattr(exc, "status_code", None) in REAUTH_STATUSES:
        _flag_for_reauth(publication.account)
    return publication.state


def _flag_for_reauth(account):
    """The token was rejected: stop trying and ask for a reconnect.

    Every other publication for this account preflights as blocked from here
    on, which is the visible-failure half of "nothing is skipped silently".
    """
    account.status = PublishingAccount.Status.NEEDS_REAUTH
    account.save(update_fields=["status"])
    logger.warning("account %s needs reconnecting", account.pk)


def _retry_later(publication, exc):
    """Back off, or give up once the schedule is exhausted."""
    publication.attempts += 1
    publication.last_error = str(exc)
    if publication.attempts > len(RETRY_BACKOFF):
        publication.state = Publication.State.FAILED
        publication.save(update_fields=["state", "attempts", "last_error"])
        logger.warning("publication %s exhausted retries: %s", publication.pk, exc)
        return publication.state
    publication.state = Publication.State.PENDING
    publication.claimed_at = None
    publication.next_attempt_at = (
        timezone.now() + RETRY_BACKOFF[publication.attempts - 1]
    )
    publication.save(
        update_fields=[
            "state",
            "attempts",
            "last_error",
            "claimed_at",
            "next_attempt_at",
        ]
    )
    return publication.state
