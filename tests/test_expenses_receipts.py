"""Receipt encryption + serve-decrypt round trip + form validation."""

import io
import os
import shutil
import tempfile
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from expenses.forms import ExpenseForm
from expenses.models import (
    RECEIPT_MAX_BYTES,
    Category,
    Event,
    Expense,
    Participant,
)
from expenses.permissions import EXPENSES_GROUP
from expenses.storage import EncryptedFileSystemStorage

User = get_user_model()


@pytest.fixture
def media_root():
    """Per-test MEDIA_ROOT so encrypted files don't bleed between tests."""
    tmp = tempfile.mkdtemp(prefix="expenses-test-")
    with override_settings(MEDIA_ROOT=tmp):
        yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def storage(media_root):
    return EncryptedFileSystemStorage(location=os.path.join(media_root, "enc"))


@pytest.fixture
def event(db):
    owner = User.objects.create_user(username="o")
    return Event.objects.create(name="Trip", owner=owner, base_currency="USD")


@pytest.fixture
def participants(event):
    parts = []
    for name in ("Alice", "Bob"):
        u = User.objects.create_user(username=name.lower())
        parts.append(Participant.objects.create(event=event, user=u, display_name=name))
    return parts


@pytest.fixture
def category(db):
    return Category.objects.create(name="Test")


def test_storage_encrypts_at_rest_and_decrypts_on_read(storage, media_root):
    """Bytes on disk are ciphertext; ._open() returns plaintext."""
    name = storage.save("a.txt", io.BytesIO(b"hello world"))
    on_disk = open(os.path.join(storage.location, name), "rb").read()
    assert b"hello world" not in on_disk
    decrypted = storage.open(name).read()
    assert decrypted == b"hello world"


def test_storage_url_returns_none(storage):
    """url() returns None so admin doesn't crash, but there's no public URL.
    Receipts are served only via the receipt_download view."""
    assert storage.url("anything") is None


def _form_data(payer, participants, category):
    return {
        "description": "lunch",
        "category": category.pk,
        "original_amount": "20.00",
        "original_currency": "USD",
        "payer": payer.pk,
        "paid_at": date(2026, 5, 1),
        "shared_by": [p.pk for p in participants],
    }


def test_receipt_upload_round_trips_through_form(
    media_root, event, participants, category
):
    payer, *_ = participants
    upload = SimpleUploadedFile(
        "lunch.png", b"\x89PNG\r\n\x1a\nfakebytes", content_type="image/png"
    )
    form = ExpenseForm(
        _form_data(payer, participants, category),
        files={"receipt": upload},
        event=event,
    )
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.receipt
    assert expense.receipt_original_filename == "lunch.png"
    assert expense.receipt_content_type == "image/png"
    assert expense.receipt.read() == b"\x89PNG\r\n\x1a\nfakebytes"


def test_receipt_rejects_oversized_file(event, participants, category):
    payer, *_ = participants
    upload = SimpleUploadedFile(
        "huge.pdf",
        b"X" * (RECEIPT_MAX_BYTES + 1),
        content_type="application/pdf",
    )
    form = ExpenseForm(
        _form_data(payer, participants, category),
        files={"receipt": upload},
        event=event,
    )
    assert not form.is_valid()
    assert "receipt" in form.errors


def test_receipt_rejects_disallowed_extension(event, participants, category):
    payer, *_ = participants
    upload = SimpleUploadedFile(
        "evil.exe", b"MZ\x90\x00", content_type="application/octet-stream"
    )
    form = ExpenseForm(
        _form_data(payer, participants, category),
        files={"receipt": upload},
        event=event,
    )
    assert not form.is_valid()
    assert "receipt" in form.errors


def test_receipt_download_serves_decrypted_to_participant(
    client, media_root, event, participants, category
):
    payer, other = participants
    upload = SimpleUploadedFile(
        "r.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
    )
    form = ExpenseForm(
        _form_data(payer, participants, category),
        files={"receipt": upload},
        event=event,
    )
    assert form.is_valid()
    expense = form.save()

    group, _ = Group.objects.get_or_create(name=EXPENSES_GROUP)
    payer.user.groups.add(group)
    payer.user.set_password("pw")
    payer.user.save()
    client.login(username=payer.user.username, password="pw")

    response = client.get(
        reverse(
            "expenses:receipt_download",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == b"%PDF-1.4 fake"


def test_expense_create_view_persists_uploaded_receipt(
    client, media_root, event, participants, category
):
    """Regression: the view must pass request.FILES into the form, or
    the FileField never gets the upload and receipt stays empty."""
    payer, *_ = participants
    group, _ = Group.objects.get_or_create(name=EXPENSES_GROUP)
    payer.user.groups.add(group)
    payer.user.set_password("pw")
    payer.user.save()
    client.login(username=payer.user.username, password="pw")

    upload = SimpleUploadedFile("view.png", b"\x89PNGdata", content_type="image/png")
    response = client.post(
        reverse("expenses:expense_create", kwargs={"event_id": event.pk}),
        {
            "description": "via view",
            "category": category.pk,
            "original_amount": "5.00",
            "original_currency": "USD",
            "payer": payer.pk,
            "paid_at": "2026-05-01",
            "shared_by": [p.pk for p in participants],
            "receipt": upload,
        },
    )
    assert response.status_code == 302
    expense = Expense.objects.get(description="via view")
    assert expense.receipt
    assert expense.receipt_original_filename == "view.png"


def test_receipt_download_blocked_for_non_participant(
    client, media_root, event, participants, category
):
    payer, *_ = participants
    upload = SimpleUploadedFile("r.png", b"PNGdata", content_type="image/png")
    form = ExpenseForm(
        _form_data(payer, participants, category),
        files={"receipt": upload},
        event=event,
    )
    assert form.is_valid()
    expense = form.save()

    outsider = User.objects.create_user(username="rando", password="pw")
    group, _ = Group.objects.get_or_create(name=EXPENSES_GROUP)
    outsider.groups.add(group)
    client.login(username="rando", password="pw")

    response = client.get(
        reverse(
            "expenses:receipt_download",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 404
