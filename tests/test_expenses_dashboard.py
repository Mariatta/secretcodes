"""Expenses overview stats + dashboard charts: selectors and views."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from expenses.models import Category, Event, Expense, ExpenseShare, Participant
from expenses.services.breakdown import event_breakdown, event_stats

User = get_user_model()


@pytest.fixture
def expenses_perm(db):
    return Permission.objects.get(
        codename="access_expenses", content_type__app_label="expenses"
    )


def _login(client, username, password="pw"):
    user = User.objects.create_user(username=username, password=password)
    client.login(username=username, password=password)
    return user


def _add_expense(event, *, description, category, payer, amount, day, shares, by):
    expense = Expense(
        event=event,
        description=description,
        category=category,
        original_amount=Decimal(amount),
        original_currency="USD",
        payer=payer,
        paid_at=date(2026, 5, day),
        created_by=by,
    )
    expense.save()
    for participant, share in shares:
        ExpenseShare.objects.create(
            expense=expense, participant=participant, share_amount=Decimal(share)
        )
    return expense


def _seed_trip():
    """An event with three expenses across two categories, payers, and dates."""
    owner = User.objects.create_user(username="dash_owner")
    event = Event.objects.create(name="Trip", owner=owner, base_currency="USD")
    alice = Participant.objects.create(event=event, user=owner, display_name="Alice")
    bob = Participant.objects.create(event=event, display_name="Bob")
    food, _ = Category.objects.get_or_create(name="Food")
    lodging, _ = Category.objects.get_or_create(name="Lodging")
    _add_expense(
        event,
        description="Dinner",
        category=food,
        payer=alice,
        amount="60.00",
        day=1,
        shares=[(alice, "30.00"), (bob, "30.00")],
        by=owner,
    )
    _add_expense(
        event,
        description="Hotel",
        category=lodging,
        payer=bob,
        amount="200.00",
        day=2,
        shares=[(alice, "100.00"), (bob, "100.00")],
        by=owner,
    )
    _add_expense(
        event,
        description="Lunch",
        category=food,
        payer=alice,
        amount="40.00",
        day=1,
        shares=[(alice, "20.00"), (bob, "20.00")],
        by=owner,
    )
    return event


def test_stats_empty_event(db):
    owner = User.objects.create_user(username="empty_owner")
    event = Event.objects.create(name="Empty", owner=owner, base_currency="USD")
    Participant.objects.create(event=event, user=owner, display_name="Solo")

    stats = event_stats(event)

    assert stats["total"] == 0.0  # exercises _f(None)
    assert stats["count"] == 0
    assert stats["average"] == 0.0
    assert stats["largest"] == 0.0
    assert stats["first_date"] is None
    assert stats["categories"] == 0
    assert stats["participants"] == 1


def test_stats_aggregates(db):
    stats = event_stats(_seed_trip())

    assert stats["total"] == 300.0
    assert stats["count"] == 3
    assert stats["average"] == 100.0
    assert stats["largest"] == 200.0
    assert stats["categories"] == 2
    assert stats["participants"] == 2
    assert stats["first_date"] == date(2026, 5, 1)
    assert stats["last_date"] == date(2026, 5, 2)


def test_breakdown_empty_event(db):
    owner = User.objects.create_user(username="bd_empty")
    event = Event.objects.create(name="Empty", owner=owner, base_currency="USD")

    data = event_breakdown(event)

    assert data["currency"] == "USD"
    assert data["by_category"] == []
    assert data["by_payer"] == []
    assert data["by_share"] == []
    assert data["over_time"] == []


def test_breakdown_aggregates(db):
    data = event_breakdown(_seed_trip())

    # Sorted by total, descending.
    assert data["by_category"] == [
        {"label": "Lodging", "value": 200.0},
        {"label": "Food", "value": 100.0},
    ]
    assert data["by_payer"] == [
        {"label": "Bob", "value": 200.0},
        {"label": "Alice", "value": 100.0},
    ]
    # Alice and Bob each consumed 150.
    assert {row["label"]: row["value"] for row in data["by_share"]} == {
        "Alice": 150.0,
        "Bob": 150.0,
    }
    assert data["over_time"] == [
        {"label": "May 01", "value": 100.0},
        {"label": "May 02", "value": 200.0},
    ]


def test_overview_shows_stat_strip(client, expenses_perm):
    user = _login(client, "ov_member")
    user.user_permissions.add(expenses_perm)
    event = Event.objects.create(name="Trip", owner=user, base_currency="USD")
    payer = Participant.objects.create(event=event, user=user, display_name="Payer")
    food, _ = Category.objects.get_or_create(name="Food")
    _add_expense(
        event,
        description="Dinner",
        category=food,
        payer=payer,
        amount="60.00",
        day=1,
        shares=[(payer, "60.00")],
        by=user,
    )

    response = client.get(
        reverse("expenses:event_overview", kwargs={"event_id": event.pk})
    )

    assert response.status_code == 200
    assert b"See charts and breakdown" in response.content
    # The stats live on the overview, not a heavy chart library.
    assert b"chartjs/chart.umd.js" not in response.content


def test_dashboard_renders_charts_for_participant(client, expenses_perm):
    user = _login(client, "dash_member")
    user.user_permissions.add(expenses_perm)
    event = Event.objects.create(name="Trip", owner=user, base_currency="USD")
    payer = Participant.objects.create(event=event, user=user, display_name="Payer")
    food, _ = Category.objects.get_or_create(name="Food")
    _add_expense(
        event,
        description="Dinner",
        category=food,
        payer=payer,
        amount="60.00",
        day=1,
        shares=[(payer, "60.00")],
        by=user,
    )

    response = client.get(
        reverse("expenses:event_dashboard", kwargs={"event_id": event.pk})
    )

    assert response.status_code == 200
    assert b"By category" in response.content
    assert b'id="chart-category"' in response.content
    assert b'id="data-category"' in response.content
    assert b"chartjs/chart.umd.js" in response.content


def test_dashboard_empty_event_shows_placeholder(client, expenses_perm):
    user = _login(client, "dash_empty")
    user.user_permissions.add(expenses_perm)
    event = Event.objects.create(name="Empty", owner=user, base_currency="USD")
    Participant.objects.create(event=event, user=user, display_name="Solo")

    response = client.get(
        reverse("expenses:event_dashboard", kwargs={"event_id": event.pk})
    )

    assert response.status_code == 200
    assert b"No expenses yet" in response.content
    assert b'id="chart-category"' not in response.content
