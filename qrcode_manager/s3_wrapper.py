from django.conf import settings
import boto3
import io
import qrcode
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
        self.client.upload_fileobj(buffer, settings.AWS_STORAGE_BUCKET_NAME, filename,
                          ExtraArgs=extra_args,)

    def generate_presigned_url(self, filename, expires_in=3600):
        pre_signed_url = self.client.generate_presigned_url('get_object',
                                           Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                                                               'Key': filename,
                                                               },
                                                       ExpiresIn=expires_in)
        return pre_signed_url

    def generate_url(self, filename):
        return f"{settings.AWS_S3_ENDPOINT_URL}/{settings.AWS_STORAGE_BUCKET_NAME}/{filename}"

    def generate_qr(self, url, filename, path=None):
        if not path:
            path = "short_lived/qrcode/"
        save_path = path + filename

        buffer = io.BytesIO()

        img = qrcode.make(url)

        img.save(buffer)
        buffer.seek(0)
        self.upload_fileobj(buffer, save_path, "image/png")

        return self.generate_url(save_path)
