from django.contrib import admin

from qrcode_manager.models import DailyQRCount, QRCode

# Register your models here.
admin.site.register(QRCode)


@admin.register(DailyQRCount)
class DailyQRCountAdmin(admin.ModelAdmin):
    list_display = ("date", "count")
    ordering = ("-date",)
