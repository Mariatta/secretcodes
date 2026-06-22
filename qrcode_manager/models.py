from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now

from .forms import validate_slug_not_reserved
from .qr_image import (
    DEFAULT_BACK_COLOR,
    DEFAULT_COLOR_MASK_STYLE,
    DEFAULT_FILL_COLOR,
    DEFAULT_GRADIENT_COLOR,
    DEFAULT_MODULE_STYLE,
)
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

    description = models.CharField("description", max_length=30)
    url = models.URLField("url", unique=True)
    filename = models.CharField("filename", max_length=100, default="")
    slug = models.CharField("slug", max_length=40, blank=True, null=True, unique=True)
    visit_count = models.IntegerField("visit_count", default=0)
    last_visited = models.DateTimeField("last_visited", blank=True, null=True)
    fill_color = models.CharField(
        "fill_color", max_length=7, default=DEFAULT_FILL_COLOR
    )
    back_color = models.CharField(
        "back_color", max_length=7, default=DEFAULT_BACK_COLOR
    )
    gradient_color = models.CharField(
        "gradient_color", max_length=7, default=DEFAULT_GRADIENT_COLOR
    )
    module_style = models.CharField(
        "module_style", max_length=20, default=DEFAULT_MODULE_STYLE
    )
    color_mask_style = models.CharField(
        "color_mask_style", max_length=20, default=DEFAULT_COLOR_MASK_STYLE
    )
    logo_filename = models.CharField(
        "logo_filename", max_length=120, blank=True, default=""
    )

    class Meta:
        permissions = [
            ("create_slug_qrcode", "Can create slug-style QR codes"),
        ]

    def __str__(self):
        return self.description

    @property
    def qr_filename(self):
        if self.filename:
            return self.filename
        else:
            self.filename = self.description + ".png"
            return self.filename

    def clean(self):
        super().clean()
        if self.slug:
            try:
                validate_slug_not_reserved(self.slug)
            except ValidationError as exc:
                raise ValidationError({"slug": exc})

    @property
    def logo_key(self):
        """S3 key of the stored logo, or "" when no logo is attached."""
        if not self.logo_filename:
            return ""
        return settings.MEDIA_ROOT + "/qrcode/logos/" + self.logo_filename

    def attach_logo(self, fileobj):
        """Store the uploaded logo in S3 so later regenerations keep it.

        Must be called before `save()` — `generate_qr` fetches the logo
        back from S3 by `logo_filename`.
        """
        self.logo_filename = self.qr_filename + ".logo.png"
        S3Wrapper().upload_logo(fileobj, self.logo_key)

    def generate_qr(self):
        save_path = settings.MEDIA_ROOT + "/qrcode/"
        s3_wrapper = S3Wrapper()
        if self.slug:
            data = settings.DOMAIN_NAME + "/qr/" + self.slug
        else:
            data = self.url
        return s3_wrapper.generate_qr(
            data,
            self.qr_filename,
            save_path,
            fill_color=self.fill_color,
            back_color=self.back_color,
            gradient_color=self.gradient_color,
            module_style=self.module_style,
            color_mask_style=self.color_mask_style,
            logo_key=self.logo_key,
        )

    def save(self, *args, **kwargs):
        if self.slug:
            validate_slug_not_reserved(self.slug)
        self.generate_qr()
        super().save(*args, **kwargs)

    def get_qr_image_url(self):
        save_path = settings.MEDIA_ROOT + "/qrcode/" + self.qr_filename
        s3_wrapper = S3Wrapper()
        return s3_wrapper.generate_url(save_path)
