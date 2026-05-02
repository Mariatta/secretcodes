"""Bulk settle-up flow."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from expenses.models import (
    Category,
    Event,
    Expense,
    ExpenseShare,
    Participant,
)

User = get_user_model()


@pytest.fixture
def setup(db):
    perm = Permission.objects.get(
        codename="access_expenses", content_type__app_label="expenses"
    )
    owner = User.objects.create_user(username="owner", password="pw")
    owner.user_permissions.add(perm)
    event = Event.objects.create(name="Trip", owner=owner, base_currency="USD")
    alice = Participant.objects.create(event=event, user=owner, display_name="Alice")
    bob_user = User.objects.create_user(username="bob", password="pw")
    bob_user.user_permissions.add(perm)
    bob = Participant.objects.create(event=event, user=bob_user, display_name="Bob")
    carol_user = User.objects.create_user(username="carol", password="pw")
    carol_user.user_permissions.add(perm)
    carol = Participant.objects.create(
        event=event, user=carol_user, display_name="Carol"
    )
    category, _ = Category.objects.get_or_create(name="SettleUpTestCat")
    return {
        "event": event,
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "category": category,
        "owner_user": owner,
        "bob_user": bob_user,
    }


def _make(setup, *, payer, debtor, amount, reimbursed=False):
    expense = Expense.objects.create(
        event=setup["event"],
        description=f"meal-{payer.display_name}-{debtor.display_name}",
        category=setup["category"],
        original_amount=Decimal(amount),
        original_currency="USD",
        payer=payer,
        paid_at=date(2026, 5, 1),
    )
    return ExpenseShare.objects.create(
        expense=expense,
        participant=debtor,
        share_amount=Decimal(amount),
        reimbursed=reimbursed,
    )


def test_settle_up_flips_only_matching_pair(client, setup):
    """Only Bob → Alice shares get marked, not Carol's or Bob's-to-others."""
    client.login(username="owner", password="pw")
    bob_to_alice_a = _make(
        setup, payer=setup["alice"], debtor=setup["bob"], amount="20"
    )
    bob_to_alice_b = _make(
        setup, payer=setup["alice"], debtor=setup["bob"], amount="30"
    )
    bob_to_carol = _make(setup, payer=setup["carol"], debtor=setup["bob"], amount="40")
    carol_to_alice = _make(
        setup, payer=setup["alice"], debtor=setup["carol"], amount="50"
    )

    response = client.post(
        reverse(
            "expenses:settle_up",
            kwargs={
                "event_id": setup["event"].pk,
                "debtor_id": setup["bob"].pk,
                "creditor_id": setup["alice"].pk,
            },
        )
    )
    assert response.status_code == 302

    bob_to_alice_a.refresh_from_db()
    bob_to_alice_b.refresh_from_db()
    bob_to_carol.refresh_from_db()
    carol_to_alice.refresh_from_db()
    assert bob_to_alice_a.reimbursed is True
    assert bob_to_alice_b.reimbursed is True
    assert bob_to_carol.reimbursed is False
    assert carol_to_alice.reimbursed is False


def test_settle_up_skips_already_reimbursed(client, setup):
    client.login(username="owner", password="pw")
    paid = _make(
        setup, payer=setup["alice"], debtor=setup["bob"], amount="20", reimbursed=True
    )
    fresh = _make(setup, payer=setup["alice"], debtor=setup["bob"], amount="30")

    response = client.post(
        reverse(
            "expenses:settle_up",
            kwargs={
                "event_id": setup["event"].pk,
                "debtor_id": setup["bob"].pk,
                "creditor_id": setup["alice"].pk,
            },
        )
    )
    assert response.status_code == 302
    paid.refresh_from_db()
    fresh.refresh_from_db()
    assert paid.reimbursed is True  # was true, stays true
    assert fresh.reimbursed is True


def test_settle_up_confirmation_page_shows_total(client, setup):
    client.login(username="owner", password="pw")
    _make(setup, payer=setup["alice"], debtor=setup["bob"], amount="20")
    _make(setup, payer=setup["alice"], debtor=setup["bob"], amount="30")

    response = client.get(
        reverse(
            "expenses:settle_up",
            kwargs={
                "event_id": setup["event"].pk,
                "debtor_id": setup["bob"].pk,
                "creditor_id": setup["alice"].pk,
            },
        )
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "50" in body
    assert "Bob" in body
    assert "Alice" in body


def test_ledger_filters_by_category(client, setup):
    """?category=<id> narrows the ledger to that category only."""
    other_cat, _ = Category.objects.get_or_create(name="OtherCat")
    food = setup["category"]
    e1 = Expense.objects.create(
        event=setup["event"],
        description="dinner",
        category=food,
        original_amount=Decimal("20"),
        original_currency="USD",
        payer=setup["alice"],
        paid_at=date(2026, 5, 1),
    )
    ExpenseShare.objects.create(
        expense=e1, participant=setup["alice"], share_amount=Decimal("20")
    )
    e2 = Expense.objects.create(
        event=setup["event"],
        description="taxi",
        category=other_cat,
        original_amount=Decimal("15"),
        original_currency="USD",
        payer=setup["alice"],
        paid_at=date(2026, 5, 2),
    )
    ExpenseShare.objects.create(
        expense=e2, participant=setup["alice"], share_amount=Decimal("15")
    )
    client.login(username="owner", password="pw")
    response = client.get(
        reverse("expenses:event_ledger", kwargs={"event_id": setup["event"].pk})
        + f"?category={food.pk}"
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "dinner" in body
    assert "taxi" not in body


def test_csv_export_lists_one_row_per_share(client, setup):
    e = Expense.objects.create(
        event=setup["event"],
        description="dinner",
        category=setup["category"],
        original_amount=Decimal("30"),
        original_currency="USD",
        payer=setup["alice"],
        paid_at=date(2026, 5, 1),
    )
    ExpenseShare.objects.create(
        expense=e, participant=setup["alice"], share_amount=Decimal("10")
    )
    ExpenseShare.objects.create(
        expense=e, participant=setup["bob"], share_amount=Decimal("10")
    )
    ExpenseShare.objects.create(
        expense=e, participant=setup["carol"], share_amount=Decimal("10")
    )
    client.login(username="owner", password="pw")
    response = client.get(
        reverse("expenses:event_export_csv", kwargs={"event_id": setup["event"].pk})
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    body = response.content.decode()
    lines = [line for line in body.splitlines() if line]
    assert lines[0].startswith("expense_id,date,description")
    data_rows = lines[1:]
    assert len(data_rows) == 3
    assert all("dinner" in row for row in data_rows)


def test_settle_up_requires_event_membership(client, setup):
    other_user = User.objects.create_user(username="rando", password="pw")
    other_user.user_permissions.add(
        Permission.objects.get(
            codename="access_expenses", content_type__app_label="expenses"
        )
    )
    client.login(username="rando", password="pw")
    response = client.get(
        reverse(
            "expenses:settle_up",
            kwargs={
                "event_id": setup["event"].pk,
                "debtor_id": setup["bob"].pk,
                "creditor_id": setup["alice"].pk,
            },
        )
    )
    assert response.status_code == 404
