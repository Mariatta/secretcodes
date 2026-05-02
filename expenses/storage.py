"""Fernet-encrypted file storage for receipts.

Wraps Django's `FileSystemStorage`. On `_save` the bytes are encrypted
with `settings.FERNET_KEY` before hitting disk; on `_open` they're
decrypted back into a `ContentFile`. `url()` is blocked because the
encrypted blob would be useless directly — receipts are served by a
dedicated view that decrypts on the fly.

Same Fernet key as `availability/encryption.py`; rotating it requires
re-encrypting both surfaces.
"""

import os

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage


def _fernet():
    """Build a Fernet instance from settings.FERNET_KEY."""
    key = settings.FERNET_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class EncryptedFileSystemStorage(FileSystemStorage):
    """Encrypts on write, decrypts on read. Same path layout as parent.

    `base_location` is a property (not @cached_property) so test
    `override_settings(MEDIA_ROOT=...)` is honored — the model's
    storage instance is created at import time and would otherwise
    bake the original MEDIA_ROOT.
    """

    @property
    def base_location(self):
        if self._location is not None:
            return self._location
        return os.path.join(settings.MEDIA_ROOT, "encrypted")

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def _save(self, name, content):
        plaintext = content.read()
        ciphertext = _fernet().encrypt(plaintext)
        return super()._save(name, ContentFile(ciphertext))

    def _open(self, name, mode="rb"):
        encrypted = super()._open(name, mode).read()
        plaintext = _fernet().decrypt(encrypted)
        return ContentFile(plaintext, name=name)

    def url(self, name):
        """No public URL — receipts are only served via the decrypt view.

        Returns None so Django admin's ClearableFileInput can render
        without crashing; admin's "Currently:" link won't appear, but
        the upload widget and the dedicated receipt_download URL
        continue to work.
        """
        return None
