"""Auto-provision a short URL + QR code when a survey is published.

The short link points at the public respondent view via the existing
``qrcode_manager`` redirect (``/qr/<slug>/`` → ``QRCode.url``), so the
QR image just encodes the short URL and the redirect does the rest.
"""

import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse

from qrcode_manager.models import QRCode

from ..models import Survey


SHORT_SLUG_BYTES = 6
SHORT_SLUG_MAX_RETRIES = 8


def _s3_configured() -> bool:
    """QR generation needs the S3/Spaces stack — only configured when
    ``USE_SPACES=true`` and the AWS endpoint setting is present."""
    return getattr(settings, "AWS_S3_ENDPOINT_URL", None) is not None


def _respondent_url(survey: Survey) -> str:
    """Absolute URL of the public respondent page for a survey."""
    return settings.DOMAIN_NAME + reverse(
        "surveys:respond", kwargs={"slug": survey.slug}
    )


def _generate_unique_slug() -> str:
    """Return a URL-safe random slug not already in use as a QRCode slug.

    Retries on collision; raises if it can't find a free one in a
    handful of tries (essentially never with a 6-byte token space).
    """
    for _ in range(SHORT_SLUG_MAX_RETRIES):
        candidate = secrets.token_urlsafe(SHORT_SLUG_BYTES)
        if not QRCode.objects.filter(slug=candidate).exists():
            return candidate
    raise RuntimeError("Could not allocate a unique short slug after retries.")


@transaction.atomic
def ensure_short_url(survey: Survey) -> QRCode | None:
    """Return ``survey.short_url``, creating a QRCode on first publish.

    Only provisions for a published survey. Idempotent — re-calling on
    a survey that already has ``short_url`` set returns it unchanged.
    Once provisioned, the link persists across status changes (closing
    a survey doesn't invalidate the link; the destination just returns
    404 while it's not published).

    The first call provisions: ``QRCode.url`` = absolute respondent URL,
    ``QRCode.slug`` = a random short slug. Saving the QRCode triggers
    ``generate_qr()`` which uploads the PNG via the existing S3 wrapper.

    Skipped silently when ``USE_SPACES`` is not configured (e.g. local
    dev without S3/Spaces credentials) — saving the survey still works,
    just no QR is created. Re-call once S3 is configured to backfill.
    """
    if survey.short_url_id:
        return survey.short_url
    if survey.status != Survey.Status.PUBLISHED:
        return None
    if not _s3_configured():
        return None

    description = (survey.title or "Survey")[:30]
    for attempt in range(SHORT_SLUG_MAX_RETRIES):
        try:
            qr = QRCode.objects.create(
                description=description,
                url=_respondent_url(survey),
                slug=_generate_unique_slug(),
            )
            break
        except IntegrityError:
            if attempt == SHORT_SLUG_MAX_RETRIES - 1:
                raise
            continue

    survey.short_url = qr
    survey.save(update_fields=["short_url", "modified_date"])
    return qr
