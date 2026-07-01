"""One-time historical backfill for the QR day counter and slug ownership.

Written as a plain function taking the model classes so both the data
migration (historical models via ``apps.get_model``) and the tests (real
models) can call the exact same logic.
"""

from collections import Counter


def backfill_qr_history(QRCode, DailyQRCount, owner=None):
    """Seed the per-day counter from existing codes so the historical total
    survives a later ``purge_ephemeral_qr``, and (if ``owner`` is given)
    assign existing slug codes to that user so they show up in their history.
    """
    counts = Counter(qr.creation_date.date() for qr in QRCode.objects.all())
    for day, total in counts.items():
        DailyQRCount.objects.update_or_create(date=day, defaults={"count": total})

    if owner is not None:
        (
            QRCode.objects.filter(user__isnull=True)
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .update(user=owner)
        )
