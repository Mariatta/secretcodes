"""Event create/edit pages, the Expense Manager group, and the event list queries."""

import importlib
from datetime import date
from decimal import Decimal
from html import unescape

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from expenses.forms import EventForm
from expenses.models import Category, Event, Expense, Participant
from expenses.permissions import EXPENSE_MANAGER_GROUP, can_create_events

User = get_user_model()
seed_migration = importlib.import_module(
    "expenses.migrations.0007_expense_manager_group_and_itemized_split"
)


@pytest.fixture
def access_perm(db):
    return Permission.objects.get(
        codename="access_expenses", content_type__app_label="expenses"
    )


@pytest.fixture
def add_event_perm(db):
    return Permission.objects.get(
        codename="add_event", content_type__app_label="expenses"
    )


@pytest.fixture
def manager(client, access_perm, add_event_perm):
    """Logged-in user who may use the app and create events."""
    user = User.objects.create_user(username="manager", password="pw", first_name="Mia")
    user.user_permissions.add(access_perm, add_event_perm)
    client.login(username="manager", password="pw")
    return user


@pytest.fixture
def member(client, access_perm):
    """Logged-in user with app access only (an invited participant)."""
    user = User.objects.create_user(username="member", password="pw")
    user.user_permissions.add(access_perm)
    client.login(username="member", password="pw")
    return user


def _event_data(**overrides):
    data = {
        "name": "Japan trip",
        "start_date": "2026-11-01",
        "end_date": "2026-11-10",
        "base_currency": "usd",
        "notes": "",
        "fx-TOTAL_FORMS": "3",
        "fx-INITIAL_FORMS": "0",
        "fx-MIN_NUM_FORMS": "0",
        "fx-MAX_NUM_FORMS": "1000",
        "fx-0-currency": "jpy",
        "fx-0-rate": "0.0067",
        "fx-1-currency": "",
        "fx-1-rate": "",
        "fx-2-currency": "",
        "fx-2-rate": "",
    }
    data.update(overrides)
    return data


def _owned_event(owner, **fields):
    event = Event.objects.create(
        name="Trip", owner=owner, base_currency="USD", **fields
    )
    Participant.objects.create(event=event, user=owner, role=Participant.OWNER)
    return event


# Permission and group


def test_can_create_events_needs_both_perms(db, access_perm, add_event_perm):
    user = User.objects.create_user(username="u")
    user.user_permissions.add(add_event_perm)
    assert can_create_events(User.objects.get(pk=user.pk)) is False
    user.user_permissions.add(access_perm)
    assert can_create_events(User.objects.get(pk=user.pk)) is True


def test_seed_creates_expense_manager_group_with_add_event(db, add_event_perm):
    Group.objects.filter(name=EXPENSE_MANAGER_GROUP).delete()
    seed_migration.seed_forward(django_apps, None)
    group = Group.objects.get(name=EXPENSE_MANAGER_GROUP)
    assert list(group.permissions.all()) == [add_event_perm]
    seed_migration.seed_reverse(django_apps, None)
    assert not Group.objects.filter(name=EXPENSE_MANAGER_GROUP).exists()


# Create


def test_create_makes_owner_participant_and_redirects(client, manager):
    response = client.post(reverse("expenses:event_create"), _event_data())
    event = Event.objects.get(name="Japan trip")
    assert response.status_code == 302
    assert response.url == reverse("expenses:event_overview", args=[event.pk])
    assert event.owner == manager
    assert event.base_currency == "USD"
    assert event.fx_rates == {"JPY": "0.0067"}
    owner_row = event.participants.get()
    assert owner_row.user == manager
    assert owner_row.role == Participant.OWNER
    assert owner_row.display_name == "Mia"
    assert owner_row.joined_at is not None
    # The creator can open the event they just made.
    assert client.get(response.url).status_code == 200


def test_create_get_defaults_to_usd_without_archive_field(client, manager):
    response = client.get(reverse("expenses:event_create"))
    form = response.context["form"]
    assert response.status_code == 200
    assert form.fields["base_currency"].initial == "USD"
    assert "is_archived" not in form.fields
    assert len(response.context["fx_formset"].forms) == 3


def test_create_forbidden_without_add_event(client, member):
    response = client.get(reverse("expenses:event_create"))
    assert response.status_code == 302
    assert "login" in response.url
    response = client.post(reverse("expenses:event_create"), _event_data())
    assert response.status_code == 302
    assert not Event.objects.filter(name="Japan trip").exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"end_date": "2026-10-01"}, "End date can't be before the start date."),
        ({"base_currency": "US"}, "Use a three-letter currency code"),
        ({"fx-0-currency": "JP"}, "Use a three-letter currency code"),
        ({"fx-0-rate": "0"}, "Rate must be greater than zero."),
        ({"fx-0-rate": ""}, "Enter a rate for this currency."),
        ({"fx-0-currency": ""}, "Enter the currency this rate is for."),
        (
            {"fx-1-currency": "JPY", "fx-1-rate": "0.007"},
            "JPY is listed more than once.",
        ),
        ({"fx-0-currency": "USD"}, "USD is the base currency"),
    ],
)
def test_create_validation(client, manager, overrides, message):
    response = client.post(reverse("expenses:event_create"), _event_data(**overrides))
    assert response.status_code == 200
    assert message in unescape(response.content.decode())
    assert not Event.objects.exists()


def test_create_stores_whole_rates_without_exponent(client, manager):
    client.post(
        reverse("expenses:event_create"),
        _event_data(**{"fx-0-currency": "JPY", "fx-0-rate": "150"}),
    )
    assert Event.objects.get().fx_rates == {"JPY": "150"}


def test_create_skips_blank_fx_rows(client, manager):
    client.post(
        reverse("expenses:event_create"),
        _event_data(**{"fx-0-currency": "", "fx-0-rate": ""}),
    )
    assert Event.objects.get().fx_rates == {}


# Edit


def test_edit_owner_updates_details_rates_and_archive(client, manager):
    event = _owned_event(manager, fx_rates={"EUR": "1.08"})
    data = _event_data(
        name="Renamed",
        is_archived="on",
        **{
            "fx-INITIAL_FORMS": "1",
            "fx-TOTAL_FORMS": "4",
            "fx-0-currency": "EUR",
            "fx-0-rate": "1.1",
            "fx-1-currency": "JPY",
            "fx-1-rate": "0.0067",
            "fx-3-currency": "",
            "fx-3-rate": "",
        },
    )
    response = client.post(reverse("expenses:event_edit", args=[event.pk]), data)
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.name == "Renamed"
    assert event.is_archived is True
    assert event.fx_rates == {"EUR": "1.1", "JPY": "0.0067"}
    # Base currency is locked: the submitted lowercase "usd" is ignored.
    assert event.base_currency == "USD"


def test_edit_get_prefills_rates_and_shows_archive(client, manager):
    event = _owned_event(manager, fx_rates={"JPY": 0.0067})
    response = client.get(reverse("expenses:event_edit", args=[event.pk]))
    form = response.context["form"]
    assert response.status_code == 200
    assert "is_archived" in form.fields
    assert form.fields["base_currency"].disabled is True
    first = response.context["fx_formset"].forms[0]
    assert first.initial == {"currency": "JPY", "rate": 0.0067}
    assert first.locked is False


def test_edit_keeps_rate_of_currency_used_by_an_expense(client, manager):
    event = _owned_event(manager, fx_rates={"JPY": 0.0067, "EUR": "1.08"})
    Expense.objects.create(
        event=event,
        description="ramen",
        category=Category.objects.create(name="EventsTestFood"),
        original_amount=Decimal("1000"),
        original_currency="JPY",
        payer=event.participants.get(),
        paid_at=date(2026, 11, 2),
    )
    response = client.get(reverse("expenses:event_edit", args=[event.pk]))
    forms = {f.initial["currency"]: f for f in response.context["fx_formset"].forms[:2]}
    assert forms["JPY"].locked is True
    assert forms["EUR"].locked is False
    assert "Used by existing expenses" in response.content.decode()

    # Initial rows are sorted by code: EUR is row 0, JPY row 1. Try to
    # change and to clear the locked JPY row; both are ignored.
    data = _event_data(
        **{
            "fx-INITIAL_FORMS": "2",
            "fx-0-currency": "EUR",
            "fx-0-rate": "1.2",
            "fx-1-currency": "",
            "fx-1-rate": "",
        }
    )
    client.post(reverse("expenses:event_edit", args=[event.pk]), data)
    event.refresh_from_db()
    assert event.fx_rates == {"EUR": "1.2", "JPY": 0.0067}


def test_edit_forbidden_for_non_owner_participant(client, member, access_perm):
    owner = User.objects.create_user(username="owner")
    event = _owned_event(owner)
    Participant.objects.create(event=event, user=member)
    response = client.get(reverse("expenses:event_edit", args=[event.pk]))
    assert response.status_code == 403


def test_edit_invalid_rerenders(client, manager):
    event = _owned_event(manager)
    response = client.post(
        reverse("expenses:event_edit", args=[event.pk]),
        _event_data(end_date="2026-10-01"),
    )
    assert response.status_code == 200
    assert response.context["mode"] == "edit"


def test_event_form_rejects_rate_rows_when_formset_invalid(manager):
    form = EventForm(_event_data(**{"fx-0-rate": "-1"}), owner=manager)
    assert form.is_valid() is False
    assert form.fx_formset.is_valid() is False


# Event list


def test_list_shows_new_event_button_only_to_managers(client, manager):
    response = client.get(reverse("expenses:event_list"))
    body = response.content.decode()
    assert reverse("expenses:event_create") in body
    assert "Create one to start splitting costs." in body


def test_list_hides_new_event_button_from_members(client, member):
    response = client.get(reverse("expenses:event_list"))
    body = response.content.decode()
    assert reverse("expenses:event_create") not in body
    assert "Ask an admin to add you to one." in body


def test_list_stats_are_annotated(client, manager):
    event = _owned_event(manager)
    Participant.objects.create(event=event, display_name="Guest")
    category = Category.objects.create(name="EventsTestStats")
    for amount in ("10.50", "-2.25"):
        Expense.objects.create(
            event=event,
            description="x",
            category=category,
            original_amount=Decimal(amount),
            original_currency="USD",
            payer=event.participants.get(user=manager),
            paid_at=date(2026, 11, 2),
        )
    _owned_event(manager)
    events = {
        e.pk: e for e in client.get(reverse("expenses:event_list")).context["events"]
    }
    assert events[event.pk].participant_count == 2
    assert events[event.pk].total_spent == Decimal("8.25")
    empty = next(e for pk, e in events.items() if pk != event.pk)
    assert empty.participant_count == 1
    assert empty.total_spent == Decimal("0")


def test_list_query_count_does_not_scale_with_events(client, manager):
    def count():
        with CaptureQueriesContext(connection) as ctx:
            client.get(reverse("expenses:event_list"))
        return len(ctx.captured_queries)

    _owned_event(manager)
    one = count()
    for _ in range(4):
        _owned_event(manager)
    assert count() == one


def test_create_form_labels_and_single_fx_example(client, manager):
    response = client.get(reverse("expenses:event_create"))
    form = response.context["form"]
    assert form.fields["start_date"].label == "Start date"
    assert form.fields["base_currency"].label == "Base currency"
    rows = response.context["fx_formset"].forms
    assert "placeholder" in rows[0].fields["currency"].widget.attrs
    assert all(
        "placeholder" not in row.fields["currency"].widget.attrs for row in rows[1:]
    )
