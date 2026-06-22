import io

import boto3
from django.conf import settings
from PIL import Image

from .qr_image import build_qr_png


class S3Wrapper:
    def __init__(self):
        self.session = boto3.session.Session()
        self.client = self.session.client(
            "s3",
            region_name="nyc3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    def upload_fileobj(self, buffer, filename, content_type, extra_args=None):
        extra_args = extra_args or settings.AWS_S3_OBJECT_PARAMETERS
        extra_args["ContentType"] = content_type
        extra_args["ACL"] = settings.AWS_DEFAULT_ACL
        self.client.upload_fileobj(
            buffer,
            settings.AWS_STORAGE_BUCKET_NAME,
            filename,
            ExtraArgs=extra_args,
        )

    def download_fileobj(self, filename):
        buffer = io.BytesIO()
        self.client.download_fileobj(settings.AWS_STORAGE_BUCKET_NAME, filename, buffer)
        buffer.seek(0)
        return buffer

    def generate_presigned_url(self, filename, expires_in=3600):
        pre_signed_url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": filename,
            },
            ExpiresIn=expires_in,
        )
        return pre_signed_url

    def generate_url(self, filename):
        return f"{settings.AWS_S3_ENDPOINT_URL}/{settings.AWS_STORAGE_BUCKET_NAME}/{filename}"

    def upload_logo(self, fileobj, filename):
        """Normalize an uploaded logo to RGBA PNG and store it.

        Kept as PNG regardless of the upload format so regeneration never
        has to guess the content type, and RGBA so palette/CMYK uploads
        survive the PNG save.
        """
        img = Image.open(fileobj).convert("RGBA")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        self.upload_fileobj(buffer, filename, "image/png")

    def generate_qr(
        self,
        url,
        filename,
        path=None,
        fill_color=None,
        back_color=None,
        gradient_color=None,
        module_style=None,
        color_mask_style=None,
        logo_key=None,
    ):
        if not path:
            path = "short_lived/qrcode/"
        save_path = path + filename

        logo = None
        if logo_key:
            logo = Image.open(self.download_fileobj(logo_key))

        buffer = build_qr_png(
            url,
            fill_color=fill_color,
            back_color=back_color,
            gradient_color=gradient_color,
            module_style=module_style,
            color_mask_style=color_mask_style,
            logo=logo,
        )
        self.upload_fileobj(buffer, save_path, "image/png")

        return self.generate_url(save_path)
