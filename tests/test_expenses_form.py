"""ExpenseForm: equal-split share creation, rounding, and FX validation."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from expenses.forms import ExpenseForm
from expenses.models import Category, Event, ExpenseShare, Participant

User = get_user_model()


@pytest.fixture
def event(db):
    owner = User.objects.create_user(username="owner")
    event = Event.objects.create(
        name="Trip",
        owner=owner,
        base_currency="USD",
        fx_rates={"JPY": "0.0067"},
    )
    Category.objects.create(name="TestFood")
    return event


@pytest.fixture
def participants(event):
    parts = []
    for name in ("Alice", "Bob", "Carol"):
        u = User.objects.create_user(username=name.lower())
        parts.append(Participant.objects.create(event=event, user=u, display_name=name))
    return parts


@pytest.fixture
def category():
    return Category.objects.get(name="TestFood")


def _form_data(payer, participants, *, amount, currency, category):
    return {
        "description": "dinner",
        "category": category.pk,
        "original_amount": amount,
        "original_currency": currency,
        "payer": payer.pk,
        "paid_at": date(2026, 5, 1),
        "shared_by": [p.pk for p in participants],
    }


def test_equal_split_three_ways_clean_division(event, participants, category):
    """$30 split 3 ways = $10 each."""
    payer, *_ = participants
    data = _form_data(
        payer, participants, amount="30.00", currency="USD", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    shares = list(ExpenseShare.objects.filter(expense=expense))
    assert len(shares) == 3
    assert all(s.share_amount == Decimal("10.00") for s in shares)


def test_equal_split_payer_absorbs_rounding_remainder(event, participants, category):
    """$10 / 3 = $3.33 each; payer's share is $3.34 to balance the cent."""
    payer, *others = participants
    data = _form_data(
        payer, participants, amount="10.00", currency="USD", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    shares = {s.participant_id: s.share_amount for s in expense.shares.all()}
    assert shares[payer.pk] == Decimal("3.34")
    for other in others:
        assert shares[other.pk] == Decimal("3.33")
    assert sum(shares.values()) == Decimal("10.00")


def test_currency_must_be_in_event_fx_rates(event, participants, category):
    """Foreign currency without an FX entry is rejected."""
    payer, *_ = participants
    data = _form_data(
        payer, participants, amount="100", currency="EUR", category=category
    )
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert "original_currency" in form.errors


def test_foreign_currency_converted_to_base(event, participants, category):
    """JPY at 0.0067 is converted into USD base_amount."""
    payer, *_ = participants
    data = _form_data(
        payer, participants, amount="1000", currency="JPY", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.base_amount == Decimal("6.70")


def test_subset_split_creates_only_selected_shares(event, participants, category):
    """Unchecking a participant excludes them from the split."""
    payer, *others = participants
    subset = [payer, others[0]]
    data = _form_data(payer, subset, amount="20.00", currency="USD", category=category)
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    share_pids = set(expense.shares.values_list("participant_id", flat=True))
    assert share_pids == {payer.pk, others[0].pk}


def test_empty_split_rejected(event, participants, category):
    """Cannot save an expense with no participants in the split."""
    payer, *_ = participants
    data = _form_data(payer, [], amount="10.00", currency="USD", category=category)
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert "shared_by" in form.errors


def test_edit_recreates_shares_with_new_split(event, participants, category):
    """Editing to drop a participant removes their share row."""
    payer, *others = participants
    create = ExpenseForm(
        _form_data(
            payer, participants, amount="30.00", currency="USD", category=category
        ),
        event=event,
    )
    assert create.is_valid()
    expense = create.save()
    assert expense.shares.count() == 3

    subset = [payer, others[0]]
    edit = ExpenseForm(
        _form_data(payer, subset, amount="20.00", currency="USD", category=category),
        instance=expense,
        event=event,
    )
    assert edit.is_valid(), edit.errors
    edit.save()
    pids = set(expense.shares.values_list("participant_id", flat=True))
    assert pids == {payer.pk, others[0].pk}
    assert sum(s.share_amount for s in expense.shares.all()) == Decimal("20.00")


def test_event_form_locks_base_currency_after_creation(event):
    """On edit, base_currency input is disabled."""
    from expenses.forms import EventForm

    form = EventForm(instance=event)
    assert form.fields["base_currency"].disabled is True


def test_payer_not_in_split_first_participant_absorbs_remainder(
    event, participants, category
):
    """When payer isn't in the split, the first listed participant gets
    the rounding remainder so totals reconcile."""
    payer, alice, bob = participants
    data = _form_data(
        payer, [alice, bob], amount="10.01", currency="USD", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    shares = {s.participant_id: s.share_amount for s in expense.shares.all()}
    assert sum(shares.values()) == Decimal("10.01")
    assert payer.pk not in shares
    assert len(shares) == 2


def test_payer_not_in_split_no_remainder_keeps_shares_even(
    event, participants, category
):
    """Payer-not-in-split path with a clean division — early-return branch."""
    payer, alice, bob = participants
    data = _form_data(
        payer, [alice, bob], amount="10.00", currency="USD", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    shares = {s.participant_id: s.share_amount for s in expense.shares.all()}
    assert shares[alice.pk] == Decimal("5.00")
    assert shares[bob.pk] == Decimal("5.00")


def test_receipt_rejects_disallowed_content_type(event, participants, category):
    """Even if extension passes, content-type whitelist still applies."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    payer, *_ = participants
    upload = SimpleUploadedFile(
        "looks.jpg", b"\xff\xd8\xff\xe0fake", content_type="application/x-fake"
    )
    data = _form_data(
        payer, participants, amount="10.00", currency="USD", category=category
    )
    form = ExpenseForm(data, files={"receipt": upload}, event=event)
    assert not form.is_valid()
    assert "receipt" in form.errors


def test_signup_form_rejects_weak_password(event):
    """Django's password validators reject obvious passwords."""
    from expenses.forms import AcceptInviteSignupForm

    form = AcceptInviteSignupForm(
        {
            "username": "weakuser",
            "password1": "abc",
            "password2": "abc",
        },
        email="weak@example.com",
    )
    assert not form.is_valid()
    assert "password1" in form.errors


def test_invitation_form_rejects_existing_participant_email(event, participants):
    """Inviting an email that belongs to an existing participant is blocked."""
    from expenses.forms import InvitationForm

    payer, *_ = participants
    payer.user.email = "existing@example.com"
    payer.user.save()
    form = InvitationForm(
        {"email": "existing@example.com", "display_name": ""},
        event=event,
        inviter=payer.user,
    )
    assert not form.is_valid()
    assert "email" in form.errors


def test_edit_preserves_reimbursed_for_remaining_participants(
    event, participants, category
):
    """Reimbursement state survives edit if the participant is still in the split."""
    payer, alice, _bob = participants
    create = ExpenseForm(
        _form_data(
            payer, participants, amount="30.00", currency="USD", category=category
        ),
        event=event,
    )
    create.is_valid()
    expense = create.save()

    alice_share = expense.shares.get(participant=alice)
    alice_share.reimbursed = True
    alice_share.save()

    edit = ExpenseForm(
        _form_data(
            payer, participants, amount="60.00", currency="USD", category=category
        ),
        instance=expense,
        event=event,
    )
    edit.is_valid()
    edit.save()

    assert expense.shares.get(participant=alice).reimbursed is True
