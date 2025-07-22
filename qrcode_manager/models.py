import qrcode
from django.db import models
from django.utils.timezone import now
from django.conf import settings
# Create your models here.

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
    url = models.URLField("url")
    qr_img = models.ImageField("qrcode", upload_to="qrcode", blank=True, null=True)

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        qr_img = self.generate_qr()
        # qr_img.save(self.description + ".png")
        code = super().save()
        return code

    def generate_qr(self):
        img = generate_qr(self.url, self.description+".png")
        return img

def generate_qr(url, filename):
    save_path = settings.MEDIA_ROOT + "/qrcode/" + filename
    img = qrcode.make(url)
    img.save(save_path)
    return img
    # print("saved "+ )
