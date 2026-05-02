"""Smoke tests for view access gating."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from expenses.models import Category, Event, Expense, ExpenseShare, Participant
from expenses.permissions import EXPENSES_GROUP

User = get_user_model()


@pytest.fixture
def expenses_group(db):
    group, _ = Group.objects.get_or_create(name=EXPENSES_GROUP)
    return group


@pytest.fixture
def event(db):
    owner = User.objects.create_user(username="ev_owner")
    return Event.objects.create(name="Trip", owner=owner, base_currency="USD")


def _login(client, username, password="pw"):
    user = User.objects.create_user(username=username, password=password)
    client.login(username=username, password=password)
    return user


def test_event_list_landing_visible_to_anonymous(client):
    """Anonymous visitors see the public landing, not a redirect."""
    response = client.get(reverse("expenses:event_list"))
    assert response.status_code == 200
    assert b"Friends and family only" in response.content


@pytest.mark.django_db
def test_event_list_landing_visible_to_unauthorized_user(client):
    """A logged-in user not in expenses_users sees the landing too."""
    _login(client, "outsider")
    response = client.get(reverse("expenses:event_list"))
    assert response.status_code == 200
    assert b"don't have access yet" in response.content


def test_event_list_renders_for_group_member(client, expenses_group):
    user = _login(client, "insider")
    user.groups.add(expenses_group)
    response = client.get(reverse("expenses:event_list"))
    assert response.status_code == 200


def test_event_overview_hidden_from_non_participants(client, expenses_group, event):
    """Even with the group, non-participants get a 404."""
    user = _login(client, "stranger")
    user.groups.add(expenses_group)
    response = client.get(
        reverse("expenses:event_overview", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 404


def test_event_overview_visible_to_participant(client, expenses_group, event):
    user = _login(client, "member")
    user.groups.add(expenses_group)
    Participant.objects.create(event=event, user=user, display_name="Member")
    response = client.get(
        reverse("expenses:event_overview", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 200


def _make_expense(event, payer_participant, *, created_by):
    """Build a minimal Expense + a single share, bypassing the form."""
    category, _ = Category.objects.get_or_create(name="TestDeleteCat")
    expense = Expense(
        event=event,
        description="x",
        category=category,
        original_amount=Decimal("10.00"),
        original_currency="USD",
        payer=payer_participant,
        paid_at=date(2026, 5, 1),
        created_by=created_by,
    )
    expense.save()
    ExpenseShare.objects.create(
        expense=expense, participant=payer_participant, share_amount=Decimal("10.00")
    )
    return expense


def test_expense_delete_creator_succeeds(client, expenses_group, event):
    creator = _login(client, "creator")
    creator.groups.add(expenses_group)
    part = Participant.objects.create(event=event, user=creator, display_name="C")
    expense = _make_expense(event, part, created_by=creator)
    response = client.post(
        reverse(
            "expenses:expense_delete",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 302
    assert not Expense.objects.filter(pk=expense.pk).exists()


def test_expense_edit_non_creator_forbidden(client, expenses_group, event):
    """Edit requires creator or superuser, same as delete."""
    creator = User.objects.create_user(username="orig3")
    Participant.objects.create(event=event, user=creator, display_name="Orig3")
    part_creator = Participant.objects.get(user=creator)
    expense = _make_expense(event, part_creator, created_by=creator)

    other = _login(client, "other_edit")
    other.groups.add(expenses_group)
    Participant.objects.create(event=event, user=other, display_name="OtherEdit")

    response = client.get(
        reverse(
            "expenses:expense_edit",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 403
    response = client.post(
        reverse(
            "expenses:expense_edit",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        ),
        {"description": "modified"},
    )
    assert response.status_code == 403


def test_expense_edit_creator_succeeds(client, expenses_group, event):
    creator = _login(client, "creator_edit")
    creator.groups.add(expenses_group)
    part = Participant.objects.create(event=event, user=creator, display_name="C")
    expense = _make_expense(event, part, created_by=creator)
    response = client.get(
        reverse(
            "expenses:expense_edit",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 200


def test_expense_delete_non_creator_forbidden(client, expenses_group, event):
    creator = User.objects.create_user(username="orig")
    Participant.objects.create(event=event, user=creator, display_name="Orig")
    part_creator = Participant.objects.get(user=creator)
    expense = _make_expense(event, part_creator, created_by=creator)

    other = _login(client, "other")
    other.groups.add(expenses_group)
    Participant.objects.create(event=event, user=other, display_name="Other")

    response = client.post(
        reverse(
            "expenses:expense_delete",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 403
    assert Expense.objects.filter(pk=expense.pk).exists()


def test_expense_delete_superuser_succeeds(client, expenses_group, event):
    creator = User.objects.create_user(username="orig2")
    Participant.objects.create(event=event, user=creator, display_name="Orig2")
    part_creator = Participant.objects.get(user=creator)
    expense = _make_expense(event, part_creator, created_by=creator)

    admin = User.objects.create_superuser(username="root", password="pw")
    client.login(username="root", password="pw")
    response = client.post(
        reverse(
            "expenses:expense_delete",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 302
    assert not Expense.objects.filter(pk=expense.pk).exists()


def test_event_list_superuser_sees_all_events(client, expenses_group, event):
    """Superusers see every event regardless of participation."""
    admin = User.objects.create_superuser(username="rootadmin", password="pw")
    client.login(username="rootadmin", password="pw")
    response = client.get(reverse("expenses:event_list"))
    assert response.status_code == 200
    assert event.name.encode() in response.content


def test_expenses_user_required_returns_403_for_event_view(
    client, expenses_group, event
):
    """Logged-in users without the expenses_users group hitting an event-level
    URL hit the expenses_user_required gate before event participation is
    checked."""
    User.objects.create_user(username="lurker", password="pw")
    client.login(username="lurker", password="pw")
    response = client.get(
        reverse("expenses:event_overview", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 403


def test_viewer_participant_returns_none_for_anonymous(db, event):
    """Defensive check — anonymous user shouldn't reach the helper, but if
    they do, it returns None instead of querying."""
    from django.contrib.auth.models import AnonymousUser

    from expenses.views import _viewer_participant

    assert _viewer_participant(AnonymousUser(), event) is None


def test_accept_invite_get_renders_confirm_page_for_existing_user(
    client, expenses_group, event
):
    """Existing user logged in as the invited account — GET shows confirm page."""
    from expenses.models import ExpenseInvitation

    owner = User.objects.get(username="ev_owner")
    invitation = ExpenseInvitation.create(
        event=event, email="g2@x", inviter=owner, display_name="G2"
    )
    user = User.objects.create_user(username="g2user", password="pw", email="g2@x")
    user.groups.add(expenses_group)
    client.login(username="g2user", password="pw")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 200
    assert event.name.encode() in response.content


def test_expense_edit_post_persists_changes(client, expenses_group, event):
    """Edit POST runs the form save path and redirects."""
    creator = _login(client, "edit_post_user")
    creator.groups.add(expenses_group)
    part = Participant.objects.create(event=event, user=creator, display_name="C")
    expense = _make_expense(event, part, created_by=creator)
    cat = expense.category
    response = client.post(
        reverse(
            "expenses:expense_edit",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        ),
        {
            "description": "renamed",
            "category": cat.pk,
            "original_amount": "12.34",
            "original_currency": "USD",
            "payer": part.pk,
            "paid_at": "2026-05-02",
            "shared_by": [part.pk],
        },
    )
    assert response.status_code == 302
    expense.refresh_from_db()
    assert expense.description == "renamed"


def test_expense_create_get_renders_blank_form(client, expenses_group, event):
    user = _login(client, "create_get_user")
    user.groups.add(expenses_group)
    Participant.objects.create(event=event, user=user, display_name="U")
    response = client.get(
        reverse("expenses:expense_create", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 200


def test_expense_delete_get_renders_confirmation_page(client, expenses_group, event):
    creator = _login(client, "delete_get_user")
    creator.groups.add(expenses_group)
    part = Participant.objects.create(event=event, user=creator, display_name="C")
    expense = _make_expense(event, part, created_by=creator)
    response = client.get(
        reverse(
            "expenses:expense_delete",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 200
    assert b"Delete this expense" in response.content


def test_receipt_download_404_when_no_receipt(client, expenses_group, event):
    """An expense without a receipt should 404 on the download endpoint."""
    user = _login(client, "noreceipt_user")
    user.groups.add(expenses_group)
    part = Participant.objects.create(event=event, user=user, display_name="N")
    expense = _make_expense(event, part, created_by=user)
    assert not expense.receipt
    response = client.get(
        reverse(
            "expenses:receipt_download",
            kwargs={"event_id": event.pk, "expense_id": expense.pk},
        )
    )
    assert response.status_code == 404


def test_event_list_filters_to_user_events(client, expenses_group):
    """Users only see events they participate in."""
    user = _login(client, "viewer")
    user.groups.add(expenses_group)

    other_owner = User.objects.create_user(username="other_owner")
    mine = Event.objects.create(name="Mine", owner=other_owner, base_currency="USD")
    Event.objects.create(name="NotMine", owner=other_owner, base_currency="USD")
    Participant.objects.create(event=mine, user=user, display_name="Me")

    response = client.get(reverse("expenses:event_list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Mine" in content
    assert "NotMine" not in content
