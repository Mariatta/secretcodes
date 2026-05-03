"""Permission checks for the qrcode_manager app.

Slug-style QR codes are gated by `qrcode_manager.create_slug_qrcode`,
defined as a custom permission on the `QRCode` model. Assign it to
individual users (or to a custom group) via Django admin.

Templates can use `{% if perms.qrcode_manager.create_slug_qrcode %}`
directly — the `auth` context processor exposes `perms` automatically.
"""

QR_SLUG_CODENAME = "create_slug_qrcode"
QR_SLUG_PERM = f"qrcode_manager.{QR_SLUG_CODENAME}"
QR_SLUG_USER_GROUP = "QR Slug User"


def is_qr_slug_user(user):
    """True if `user` may create slug-style QR codes."""
    return user.is_authenticated and user.has_perm(QR_SLUG_PERM)
