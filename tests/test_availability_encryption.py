import pytest
from django.db import models
from django.test import override_settings

from availability.encryption import EncryptedTextField, decrypt, encrypt


def test_encrypt_decrypt_round_trip():
    ciphertext = encrypt("hello secret")
    assert ciphertext != "hello secret"
    assert decrypt(ciphertext) == "hello secret"


def test_encrypt_empty_string_returns_empty():
    assert encrypt("") == ""
    assert encrypt(None) == ""


def test_decrypt_empty_string_returns_empty():
    assert decrypt("") == ""
    assert decrypt(None) == ""


def test_fernet_key_accepts_bytes():
    with override_settings(FERNET_KEY=b"kTdjP9joWZr9JfnWHGmcQOOPxFEKfCB3_Hx7OgHD6LU="):
        ciphertext = encrypt("bytes-key")
        assert decrypt(ciphertext) == "bytes-key"


def test_field_round_trip_via_model_lifecycle():
    field = EncryptedTextField()
    prepped = field.get_prep_value("plaintext-value")
    assert prepped != "plaintext-value"
    recovered = field.from_db_value(prepped, expression=None, connection=None)
    assert recovered == "plaintext-value"


@pytest.mark.parametrize("blank_value", ["", None])
def test_field_preserves_blank_values(blank_value):
    field = EncryptedTextField()
    assert field.get_prep_value(blank_value) == blank_value
    assert (
        field.from_db_value(blank_value, expression=None, connection=None)
        == blank_value
    )


def test_field_is_subclass_of_text_field():
    assert issubclass(EncryptedTextField, models.TextField)
