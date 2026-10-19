"""The "Add several" grid: many equally split expenses in one save."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from expenses import forms as expense_forms
from expenses.models import Category, Event, Expense, Participant

User = get_user_model()


@pytest.fixture
def setup(client, db):
    perm = Permission.objects.get(
        codename="access_expenses", content_type__app_label="expenses"
    )
    user = User.objects.create_user(username="alice", password="pw")
    user.user_permissions.add(perm)
    client.login(username="alice", password="pw")
    event = Event.objects.create(
        name="Trip", owner=user, base_currency="USD", fx_rates={"JPY": "0.0067"}
    )
    alice = Participant.objects.create(event=event, user=user, display_name="Alice")
    bob = Participant.objects.create(event=event, display_name="Bob")
    category = Category.objects.create(name="BulkTestFood")
    return {"event": event, "alice": alice, "bob": bob, "category": category}


def _url(event):
    return reverse("expenses:expense_bulk", kwargs={"event_id": event.pk})


def _row(setup, index, **values):
    row = {
        "paid_at": "2026-10-19",
        "description": "",
        "category": setup["category"].pk,
        "original_amount": "",
        "original_currency": "USD",
        "payer": setup["alice"].pk,
        "shared_by": [setup["alice"].pk, setup["bob"].pk],
    }
    row.update(values)
    return {f"rows-{index}-{key}": value for key, value in row.items()}


def _post_data(setup, rows, total=5):
    data = {
        "rows-TOTAL_FORMS": str(total),
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
    }
    for index in range(total):
        data.update(_row(setup, index, **rows.get(index, {})))
    return data


def test_get_renders_five_rows_with_viewer_as_payer(client, setup):
    response = client.get(_url(setup["event"]))
    assert response.status_code == 200
    formset = response.context["formset"]
    assert len(formset.forms) == 5
    row = formset.forms[0]
    assert row.fields["payer"].initial == setup["alice"].pk
    assert row["original_currency"].value() == "USD"
    assert [code for code, _ in row.fields["original_currency"].choices] == [
        "USD",
        "JPY",
    ]
    body = response.content.decode()
    assert "data-bulk-template" in body
    assert "rows-__prefix__-description" in body


def test_post_saves_filled_rows_and_skips_blank_ones(client, setup):
    data = _post_data(
        setup,
        {
            0: {"description": "Taxi", "original_amount": "30"},
            2: {
                "description": "Snacks",
                "original_amount": "1000",
                "original_currency": "JPY",
                "payer": setup["bob"].pk,
                "shared_by": [setup["bob"].pk],
            },
        },
    )
    response = client.post(_url(setup["event"]), data)
    assert response.status_code == 302
    assert response.url == reverse(
        "expenses:event_ledger", kwargs={"event_id": setup["event"].pk}
    )
    taxi = Expense.objects.get(description="Taxi")
    assert sorted(s.share_amount for s in taxi.shares.all()) == [
        Decimal("15.00"),
        Decimal("15.00"),
    ]
    assert taxi.created_by.username == "alice"
    snacks = Expense.objects.get(description="Snacks")
    assert snacks.base_amount == Decimal("6.70")
    assert [s.participant for s in snacks.shares.all()] == [setup["bob"]]
    assert Expense.objects.count() == 2


def test_post_saves_nothing_when_one_row_is_invalid(client, setup):
    data = _post_data(
        setup,
        {
            0: {"description": "Taxi", "original_amount": "30"},
            1: {"description": "Lunch", "original_amount": ""},
        },
    )
    response = client.post(_url(setup["event"]), data)
    assert response.status_code == 200
    assert not Expense.objects.exists()
    row = response.context["formset"].forms[1]
    assert row.errors["original_amount"] == ["Enter the amount."]
    assert "is-invalid" in str(row["original_amount"])


def test_post_rejects_a_currency_without_a_rate(client, setup):
    data = _post_data(
        setup,
        {
            0: {
                "description": "Taxi",
                "original_amount": "30",
                "original_currency": "EUR",
            }
        },
    )
    response = client.post(_url(setup["event"]), data)
    assert response.status_code == 200
    assert "original_currency" in response.context["formset"].forms[0].errors


def test_post_with_only_blank_rows_asks_for_one(client, setup):
    response = client.post(_url(setup["event"]), _post_data(setup, {}))
    assert response.status_code == 200
    assert "Fill in at least one row." in response.context["formset"].non_form_errors()


def test_row_with_nobody_ticked_shows_split_error(client, setup):
    data = _post_data(
        setup, {0: {"description": "Taxi", "original_amount": "30", "shared_by": []}}
    )
    response = client.post(_url(setup["event"]), data)
    assert response.status_code == 200
    assert "Select at least one participant" in response.content.decode()


def test_participant_without_name_is_labelled_by_email(client, setup):
    Participant.objects.create(
        event=setup["event"], display_name="", invited_email="carol@example.com"
    )
    response = client.get(_url(setup["event"]))
    assert "carol@example.com" in response.content.decode()


def test_get_queries_do_not_scale_with_rows_or_people(client, setup, monkeypatch):
    def count():
        with CaptureQueriesContext(connection) as ctx:
            client.get(_url(setup["event"]))
        return len(ctx.captured_queries)

    baseline = count()
    monkeypatch.setattr(expense_forms.BulkExpenseFormSet, "extra", 10)
    for name in ("Carol", "Dan", "Erin"):
        Participant.objects.create(event=setup["event"], display_name=name)
    assert count() == baseline
