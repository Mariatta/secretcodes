"""Admin actions and custom admin methods."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from expenses.admin import EventAdmin, ExpenseAdmin
from expenses.models import (
    Category,
    Event,
    Expense,
    Participant,
)

User = get_user_model()


@pytest.fixture
def setup(db):
    owner = User.objects.create_user(username="adminowner", is_staff=True)
    event = Event.objects.create(
        name="AdminTrip",
        owner=owner,
        base_currency="USD",
        fx_rates={"JPY": "0.0067"},
    )
    payer = Participant.objects.create(event=event, user=owner, display_name="Owner")
    category, _ = Category.objects.get_or_create(name="AdminTestCat")
    return {"owner": owner, "event": event, "payer": payer, "category": category}


def _request_with_messages(user):
    """Build a request with the messages framework attached for admin actions."""
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_recompute_base_amounts_action_re_saves_expenses(setup):
    """Editing fx_rates and running the action recomputes base_amount."""
    expense = Expense.objects.create(
        event=setup["event"],
        description="lunch",
        category=setup["category"],
        original_amount=Decimal("1000"),
        original_currency="JPY",
        payer=setup["payer"],
        paid_at=date(2026, 5, 1),
    )
    assert expense.base_amount == Decimal("6.70")

    setup["event"].fx_rates = {"JPY": "0.01"}
    setup["event"].save()

    request = _request_with_messages(setup["owner"])
    admin = EventAdmin(Event, AdminSite())
    admin.recompute_base_amounts(request, Event.objects.filter(pk=setup["event"].pk))

    expense.refresh_from_db()
    assert expense.base_amount == Decimal("10.00")


def test_download_receipt_link_returns_dash_when_no_receipt(setup):
    """Without a receipt the link cell renders as a dash."""
    expense = Expense.objects.create(
        event=setup["event"],
        description="no-receipt",
        category=setup["category"],
        original_amount=Decimal("5"),
        original_currency="USD",
        payer=setup["payer"],
        paid_at=date(2026, 5, 1),
    )
    admin = ExpenseAdmin(Expense, AdminSite())
    assert admin.download_receipt_link(expense) == "—"


def test_download_receipt_link_renders_anchor_when_receipt_present(setup):
    """When a receipt is attached, the cell renders an <a> tag."""
    upload = SimpleUploadedFile("r.png", b"PNGdata", content_type="image/png")
    expense = Expense(
        event=setup["event"],
        description="with-receipt",
        category=setup["category"],
        original_amount=Decimal("5"),
        original_currency="USD",
        payer=setup["payer"],
        paid_at=date(2026, 5, 1),
        receipt_original_filename="r.png",
        receipt_content_type="image/png",
    )
    expense.receipt = upload
    expense.save()
    admin = ExpenseAdmin(Expense, AdminSite())
    rendered = admin.download_receipt_link(expense)
    assert "<a " in rendered
    assert "r.png" in rendered


def test_download_receipt_link_handles_unsaved_object(setup):
    """Passing an unsaved Expense returns the dash safely."""
    admin = ExpenseAdmin(Expense, AdminSite())
    assert admin.download_receipt_link(Expense()) == "—"
    assert admin.download_receipt_link(None) == "—"
