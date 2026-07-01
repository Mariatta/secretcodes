import pytest
from django.utils import timezone

from qrcode_manager.backfill import backfill_qr_history
from qrcode_manager.models import DailyQRCount, QRCode


@pytest.mark.django_db
def test_backfill_seeds_counter_and_assigns_slug_owner(django_user_model):
    owner = django_user_model.objects.create_superuser("admin", password="p")
    ephemeral = QRCode.objects.create(url="https://a.example", description="a")
    slug_qr = QRCode.objects.create(url="https://b.example", description="b", slug="s1")
    # Push the ephemeral one to a different day so it buckets separately.
    QRCode.objects.filter(pk=ephemeral.pk).update(
        creation_date=timezone.now() - timezone.timedelta(days=1)
    )

    backfill_qr_history(QRCode, DailyQRCount, owner=owner)

    assert DailyQRCount.objects.count() == 2  # two distinct days
    assert sum(DailyQRCount.objects.values_list("count", flat=True)) == 2
    slug_qr.refresh_from_db()
    ephemeral.refresh_from_db()
    assert slug_qr.user == owner  # slug code handed to the owner
    assert ephemeral.user is None  # ephemeral one stays unowned (will be purged)


@pytest.mark.django_db
def test_backfill_without_owner_only_seeds_counter():
    QRCode.objects.create(url="https://a.example", description="a", slug="s1")
    backfill_qr_history(QRCode, DailyQRCount, owner=None)
    assert DailyQRCount.objects.count() == 1
    assert QRCode.objects.get(slug="s1").user is None
