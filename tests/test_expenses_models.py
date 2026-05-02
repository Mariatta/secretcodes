"""Model-level tests: __str__, save() behaviors, edge-case branches."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from expenses.models import (
    Category,
    Event,
    Expense,
    ExpenseInvitation,
    ExpenseShare,
    Participant,
)

User = get_user_model()


@pytest.fixture
def setup(db):
    owner = User.objects.create_user(username="modelowner", first_name="OwnerFirst")
    event = Event.objects.create(
        name="ModelTrip",
        owner=owner,
        base_currency="USD",
        fx_rates={"JPY": "0.0067"},
    )
    category, _ = Category.objects.get_or_create(name="ModelTestCat")
    return {"owner": owner, "event": event, "category": category}


def test_event_str_returns_name(setup):
    assert str(setup["event"]) == "ModelTrip"


def test_event_rate_for_returns_one_for_base(setup):
    assert setup["event"].rate_for("USD") == Decimal("1")


def test_event_rate_for_returns_decimal_for_known_currency(setup):
    assert setup["event"].rate_for("JPY") == Decimal("0.0067")


def test_event_rate_for_unknown_currency_raises(setup):
    with pytest.raises(ValidationError):
        setup["event"].rate_for("EUR")


def test_category_str_returns_name():
    cat = Category(name="Lunch")
    assert str(cat) == "Lunch"


def test_participant_save_defaults_display_name_to_user_first_name(setup):
    """When display_name is blank, it falls back to user.first_name on save."""
    p = Participant.objects.create(
        event=setup["event"], user=setup["owner"], display_name=""
    )
    assert p.display_name == "OwnerFirst"


def test_participant_save_falls_back_to_username_when_no_first_name(setup):
    """If first_name is also empty, fall back to username."""
    user = User.objects.create_user(username="nofirst")
    p = Participant.objects.create(event=setup["event"], user=user, display_name="")
    assert p.display_name == "nofirst"


def test_participant_str_uses_display_name(setup):
    p = Participant.objects.create(
        event=setup["event"], user=setup["owner"], display_name="Mom"
    )
    assert "Mom" in str(p)
    assert setup["event"].name in str(p)


def test_expense_str_includes_amount_and_currency(setup):
    payer = Participant.objects.create(
        event=setup["event"], user=setup["owner"], display_name="P"
    )
    expense = Expense.objects.create(
        event=setup["event"],
        description="dinner",
        category=setup["category"],
        original_amount=Decimal("50.00"),
        original_currency="USD",
        payer=payer,
        paid_at=date(2026, 5, 1),
    )
    s = str(expense)
    assert "dinner" in s
    assert "50.00" in s
    assert "USD" in s


def test_expense_share_str_describes_owe(setup):
    payer = Participant.objects.create(
        event=setup["event"], user=setup["owner"], display_name="P"
    )
    expense = Expense.objects.create(
        event=setup["event"],
        description="x",
        category=setup["category"],
        original_amount=Decimal("10"),
        original_currency="USD",
        payer=payer,
        paid_at=date(2026, 5, 1),
    )
    share = ExpenseShare.objects.create(
        expense=expense, participant=payer, share_amount=Decimal("10")
    )
    s = str(share)
    assert "owes" in s


def test_expense_invitation_str_mentions_email_and_event(setup):
    invite = ExpenseInvitation.create(
        event=setup["event"],
        email="g@x",
        inviter=setup["owner"],
        display_name="G",
    )
    s = str(invite)
    assert "g@x" in s
    assert setup["event"].name in s


def test_basemodel_save_with_update_fields_appends_modified_date(setup):
    """Calling save(update_fields=[...]) should auto-include modified_date."""
    cat, _ = Category.objects.get_or_create(name="UpdateFieldsTest")
    cat.name = "UpdateFieldsTestRenamed"
    cat.save(update_fields=["name"])
    cat.refresh_from_db()
    assert cat.name == "UpdateFieldsTestRenamed"
