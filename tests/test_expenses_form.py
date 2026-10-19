"""ExpenseForm: equal-split share creation, rounding, and FX validation."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.forms import (
    AcceptInviteSignupForm,
    EventForm,
    ExpenseForm,
    InvitationForm,
)
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


def test_negative_amount_splits_into_negative_shares(event, participants, category):
    """A -$10 refund split 3 ways: -$3.33 each, the payer absorbs the cent."""
    payer, *others = participants
    data = _form_data(
        payer, participants, amount="-10.00", currency="USD", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.base_amount == Decimal("-10.00")
    shares = {s.participant_id: s.share_amount for s in expense.shares.all()}
    assert shares[payer.pk] == Decimal("-3.34")
    for other in others:
        assert shares[other.pk] == Decimal("-3.33")
    assert sum(shares.values()) == Decimal("-10.00")


def test_negative_foreign_amount_converted_to_base(event, participants, category):
    payer, *_ = participants
    data = _form_data(
        payer, participants, amount="-3000", currency="JPY", category=category
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    assert form.save().base_amount == Decimal("-20.10")


def test_amount_help_text_mentions_refunds(event):
    form = ExpenseForm(event=event)
    assert "negative amount" in form.fields["original_amount"].help_text


def test_new_expense_marks_paid_at_to_default_to_today(event, participants, category):
    """The browser fills in its own local date; the server leaves it blank."""
    form = ExpenseForm(event=event)
    assert form["paid_at"].value() is None
    assert "data-default-today" in str(form["paid_at"])
    data = _form_data(
        participants[0], participants, amount="5", currency="USD", category=category
    )
    edit = ExpenseForm(instance=ExpenseForm(data, event=event).save(), event=event)
    assert "data-default-today" not in str(edit["paid_at"])


def test_date_fields_get_today_button(event):
    expense_form = ExpenseForm(event=event)
    assert "data-today-button" in str(expense_form["paid_at"])
    event_form = EventForm(instance=event)
    assert "data-today-button" in str(event_form["start_date"])
    assert "data-today-button" in str(event_form["end_date"])


def _itemized_data(payer, participants, category, items, **extras):
    data = _form_data(payer, participants, amount="", currency="USD", category=category)
    data["split_mode"] = "itemized"
    for participant, amount in zip(participants, items):
        data[f"item_{participant.pk}"] = amount
    data.update(extras)
    return data


def test_itemized_split_adds_tax_and_tip_after_tax(event, participants, category):
    """Alice 30, Bob 20, Carol 10; 10% tax then 20% tip on the after-tax total."""
    payer, bob, carol = participants
    data = _itemized_data(
        payer,
        participants,
        category,
        ["30", "20", "10"],
        tax_percent="10",
        tip_percent="20",
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.split_mode == "itemized"
    assert expense.original_amount == Decimal("79.20")
    shares = {s.participant_id: s for s in expense.shares.all()}
    assert shares[payer.pk].share_amount == Decimal("39.60")
    assert shares[bob.pk].share_amount == Decimal("26.40")
    assert shares[carol.pk].share_amount == Decimal("13.20")
    assert shares[bob.pk].item_amount == Decimal("20.00")
    assert expense.tax_percent == Decimal("10")


def test_itemized_shares_add_up_with_rounding(event, participants, category):
    payer, *_ = participants
    data = _itemized_data(
        payer, participants, category, ["10", "10", "10"], tax_percent="8.875"
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    shares = [s.share_amount for s in expense.shares.all()]
    assert sum(shares) == expense.base_amount == Decimal("32.66")


def test_itemized_in_foreign_currency_converts_each_share(
    event, participants, category
):
    payer, *_ = participants
    data = _itemized_data(payer, participants, category, ["1000", "2000", "3000"])
    data["original_currency"] = "JPY"
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.original_amount == Decimal("6000.00")
    assert expense.base_amount == Decimal("40.20")
    shares = sorted(s.share_amount for s in expense.shares.all())
    assert shares == [Decimal("6.70"), Decimal("13.40"), Decimal("20.10")]


def test_itemized_rejects_items_for_people_not_in_split(event, participants, category):
    payer, bob, carol = participants
    data = _itemized_data(payer, participants, category, ["10", "10", "10"])
    data["shared_by"] = [payer.pk, bob.pk]
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert f"item_{carol.pk}" in form.errors


def test_itemized_needs_some_amount(event, participants, category):
    payer, *_ = participants
    data = _itemized_data(payer, participants, category, ["", "", ""])
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert "Enter what each person had" in str(form.non_field_errors())


def test_itemized_shared_amount_alone_is_enough(event, participants, category):
    payer, *_ = participants
    data = _itemized_data(
        payer, participants, category, ["", "", ""], shared_amount="30"
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    assert form.save().original_amount == Decimal("30.00")


def test_itemized_rejects_percent_over_100(event, participants, category):
    payer, *_ = participants
    data = _itemized_data(
        payer, participants, category, ["10", "", ""], tip_percent="150"
    )
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert "tip_percent" in form.errors


def test_equal_mode_requires_amount(event, participants, category):
    payer, *_ = participants
    data = _form_data(payer, participants, amount="", currency="USD", category=category)
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert form.errors["original_amount"] == ["Enter the amount."]


def test_switching_back_to_equal_clears_itemized_inputs(event, participants, category):
    payer, *_ = participants
    data = _itemized_data(
        payer, participants, category, ["10", "20", "30"], tax_percent="10"
    )
    form = ExpenseForm(data, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()

    edit = ExpenseForm(instance=expense, event=event)
    assert edit[f"item_{participants[1].pk}"].value() == Decimal("20.00")
    assert edit.is_itemized is True

    equal = _form_data(
        payer, participants, amount="60", currency="USD", category=category
    )
    equal["split_mode"] = "equal"
    form = ExpenseForm(equal, instance=expense, event=event)
    assert form.is_valid(), form.errors
    expense = form.save()
    assert expense.tax_percent is None
    assert all(s.item_amount is None for s in expense.shares.all())
    assert all(s.share_amount == Decimal("20.00") for s in expense.shares.all())


def test_participant_rows_pair_checkbox_and_item_field(event, participants):
    form = ExpenseForm(event=event)
    rows = form.participant_rows()
    assert [p.pk for p, _, _ in rows] == [p.pk for p in participants]
    participant, checkbox, item = rows[0]
    assert str(checkbox.data["value"]) == str(participant.pk)
    assert item.name == f"item_{participant.pk}"


def test_itemized_with_nobody_ticked_reports_only_the_split_error(
    event, participants, category
):
    payer, *_ = participants
    data = _itemized_data(payer, participants, category, ["", "", ""])
    data["shared_by"] = []
    form = ExpenseForm(data, event=event)
    assert not form.is_valid()
    assert form.errors["shared_by"] == [
        "Select at least one participant for the split."
    ]
    assert not form.non_field_errors()


def test_new_expense_defaults_payer_to_viewer_and_names_people_plainly(
    event, participants
):
    alice, *_ = participants
    form = ExpenseForm(event=event, user=alice.user)
    assert form.fields["payer"].initial == alice.pk
    assert form.fields["paid_at"].label == "Date"
    assert form.fields["payer"].label == "Paid by"
    assert "Alice @" not in str(form["payer"])
    assert ">Alice<" in str(form["payer"]) or "Alice</option>" in str(form["payer"])


def test_new_expense_by_non_participant_has_no_default_payer(event):
    outsider = User.objects.create_user(username="outsider")
    form = ExpenseForm(event=event, user=outsider)
    assert form.fields["payer"].initial is None
