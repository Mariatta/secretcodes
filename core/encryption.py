"""Fernet-encrypted model field, shared across apps.

The key is ``settings.FERNET_KEY``, deliberately separate from ``SECRET_KEY``
so rotating the Django secret does not orphan every stored ciphertext.

``availability.encryption`` re-exports this module: its migrations name
``availability.encryption.EncryptedTextField``, so that path has to keep
resolving.
"""

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


def _fernet():
    key = settings.FERNET_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(plaintext):
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext):
    if not ciphertext:
        return ""
    return _fernet().decrypt(ciphertext.encode()).decode()


class EncryptedTextField(models.TextField):
    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        if not value:
            return value
        return encrypt(value)
