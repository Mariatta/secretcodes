from django.db import models
from django.utils.timezone import now
from django.conf import settings

import boto3

from .s3_wrapper import S3Wrapper
class BaseModel(models.Model):
    creation_date = models.DateTimeField(
        "creation_date", editable=False, auto_now_add=True
    )
    modified_date = models.DateTimeField("modified_date", editable=False, auto_now=True)

    def save(self, *args, **kwargs):
        self.modified_date = now()
        if (
            "update_fields" in kwargs and "modified_date" not in kwargs["update_fields"]
        ):  # pragma: no cover
            kwargs["update_fields"].append("modified_date")
        super().save(*args, **kwargs)

class QRCode(BaseModel):

    description = models.CharField("description", max_length=100)
    url = models.URLField("url", unique=True)

    def __str__(self):
        return self.description

    def generate_qr(self):
        save_path = settings.MEDIA_ROOT + "/qrcode/"
        filename = f"{self.description}"
        s3_wrapper = S3Wrapper()
        img = s3_wrapper.generate_qr(self.url, filename, save_path)
        return img

    def save(self, *args, **kwargs):
        self.generate_qr()
        super().save(*args, **kwargs)

    def get_qr_image_url(self):
        save_path = settings.MEDIA_ROOT + "/qrcode/" + self.description
        s3_wrapper = S3Wrapper()
        return s3_wrapper.generate_url(save_path)
