from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from qrcode_manager.models import QRCode

PURGE_S3 = "qrcode_manager.management.commands.purge_ephemeral_qr.S3Wrapper"


@pytest.mark.django_db
def test_purge_deletes_ephemeral_keeps_slug_and_owned(django_user_model):
    user = django_user_model.objects.create_user("u", password="p")
    QRCode.objects.create(url="https://a.example", description="a")
    QRCode.objects.create(
        url="https://b.example", description="b", logo_filename="b.logo.png"
    )
    QRCode.objects.create(url="https://c.example", description="c", slug="keep")
    QRCode.objects.create(url="https://d.example", description="d", user=user)

    with patch(PURGE_S3) as mock_s3:
        call_command("purge_ephemeral_qr")

    assert set(QRCode.objects.values_list("url", flat=True)) == {
        "https://c.example",
        "https://d.example",
    }
    # "a" -> image only (1 delete); "b" -> image + logo (2 deletes)
    assert mock_s3.return_value.delete.call_count == 3


@pytest.mark.django_db
def test_purge_older_than_days_spares_recent(django_user_model):
    old = QRCode.objects.create(url="https://old.example", description="old")
    QRCode.objects.filter(pk=old.pk).update(
        creation_date=timezone.now() - timezone.timedelta(days=10)
    )
    QRCode.objects.create(url="https://new.example", description="new")

    with patch(PURGE_S3):
        call_command("purge_ephemeral_qr", "--older-than-days", "7")

    assert QRCode.objects.filter(url="https://new.example").exists()
    assert not QRCode.objects.filter(url="https://old.example").exists()
