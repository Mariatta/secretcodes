"""Delete ephemeral public QR codes and their stored images.

Public (anonymous) QR generation no longer persists anything, but earlier
public codes were saved. Those have no slug (not a redirect) and no owner
(not a saved history item), so they're safe to purge: users were always meant
to download them on creation. Slug redirects and users' saved codes are kept.

Run on a schedule to keep the backlog clear:
    python manage.py purge_ephemeral_qr                # delete all ephemeral
    python manage.py purge_ephemeral_qr --older-than-days 7
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from qrcode_manager.models import QRCode
from qrcode_manager.s3_wrapper import S3Wrapper


class Command(BaseCommand):
    help = "Delete ephemeral (no slug, no owner) public QR codes + their images."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=0,
            help="Only delete codes older than this many days (0 = all).",
        )

    def handle(self, *args, **options):
        days = options["older_than_days"]
        ephemeral = QRCode.objects.filter(user__isnull=True).filter(
            Q(slug__isnull=True) | Q(slug="")
        )
        if days:
            cutoff = timezone.now() - timezone.timedelta(days=days)
            ephemeral = ephemeral.filter(creation_date__lt=cutoff)

        s3 = S3Wrapper()
        count = 0
        for qr in ephemeral:
            s3.delete(settings.MEDIA_ROOT + "/qrcode/" + qr.qr_filename)
            if qr.logo_filename:
                s3.delete(qr.logo_key)
            qr.delete()
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Purged {count} ephemeral QR code(s)."))
