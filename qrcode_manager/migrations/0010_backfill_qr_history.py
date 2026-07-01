from django.db import migrations

from qrcode_manager.backfill import backfill_qr_history


def _forward(apps, schema_editor):
    """Seed the day counter from every code that already exists (so the total
    survives purging), and hand existing slug codes to a superuser so they
    appear in that account's QR history."""
    QRCode = apps.get_model("qrcode_manager", "QRCode")
    DailyQRCount = apps.get_model("qrcode_manager", "DailyQRCount")
    User = apps.get_model("auth", "User")
    owner = User.objects.filter(is_superuser=True).order_by("pk").first()
    backfill_qr_history(QRCode, DailyQRCount, owner=owner)


class Migration(migrations.Migration):

    dependencies = [
        ("qrcode_manager", "0009_dailyqrcount_qrcode_user_alter_qrcode_url"),
    ]

    operations = [
        migrations.RunPython(_forward, migrations.RunPython.noop),
    ]
