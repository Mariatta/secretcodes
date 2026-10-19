import re
from decimal import ROUND_HALF_UP, Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    RECEIPT_ALLOWED_CONTENT_TYPES,
    RECEIPT_ALLOWED_EXTENSIONS,
    RECEIPT_MAX_BYTES,
    Event,
    Expense,
    ExpenseInvitation,
    ExpenseShare,
    Participant,
)
from .services.splitting import CENT, allocate, itemized_amounts

User = get_user_model()


CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
DEFAULT_BASE_CURRENCY = "USD"
FX_EXTRA_ROWS = 3


def participant_label(participant):
    """How a participant is named in choices: their name, else their email."""
    return participant.display_name or participant.invited_email


class DateInputWithToday(forms.DateInput):
    """Native date picker with a "Today" shortcut added by brand/date-today.js."""

    def __init__(self, attrs=None, format=None):
        super().__init__(
            attrs={"type": "date", "data-today-button": "", **(attrs or {})},
            format=format,
        )


def _clean_currency_code(value):
    """Uppercase a currency code and require exactly three letters."""
    code = (value or "").strip().upper()
    if not CURRENCY_CODE_RE.match(code):
        raise ValidationError("Use a three-letter currency code, e.g. USD.")
    return code


class FxRateForm(forms.Form):
    """One FX rate row: how much one unit of `currency` is worth in base.

    Both fields are optional so a blank row is skipped (and clearing a
    row removes that rate). A row whose currency is already used by an
    expense is `locked`: its fields are disabled, so Django ignores any
    submitted value and keeps the stored rate.
    """

    currency = forms.CharField(
        label="Currency",
        max_length=3,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "JPY"}),
    )
    rate = forms.DecimalField(
        label="Rate into base",
        max_digits=20,
        decimal_places=10,
        required=False,
        widget=forms.NumberInput(attrs={"step": "any", "placeholder": "0.0067"}),
    )

    def __init__(self, *args, locked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked = locked
        if locked:
            for field in self.fields.values():
                field.disabled = True

    def clean_currency(self):
        value = self.cleaned_data.get("currency")
        return _clean_currency_code(value) if value else ""

    def clean_rate(self):
        rate = self.cleaned_data.get("rate")
        if rate is not None and rate <= 0:
            raise ValidationError("Rate must be greater than zero.")
        return rate

    def clean(self):
        cleaned = super().clean()
        currency, rate = cleaned.get("currency"), cleaned.get("rate")
        if currency and rate is None and "rate" not in self.errors:
            self.add_error("rate", "Enter a rate for this currency.")
        if rate is not None and not currency and "currency" not in self.errors:
            self.add_error("currency", "Enter the currency this rate is for.")
        return cleaned


class BaseFxRateFormSet(forms.BaseFormSet):
    """FX rate rows; rows for currencies in `locked` render read-only."""

    def __init__(self, *args, locked=(), **kwargs):
        self.locked = set(locked)
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        initial = self.initial[index] if index < len(self.initial or ()) else {}
        kwargs["locked"] = initial.get("currency") in self.locked
        return kwargs

    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            currency = form.cleaned_data.get("currency")
            if not currency:
                continue
            if currency in seen:
                raise ValidationError(f"{currency} is listed more than once.")
            seen.add(currency)


FxRateFormSet = forms.formset_factory(
    FxRateForm, formset=BaseFxRateFormSet, extra=FX_EXTRA_ROWS
)


class EventForm(forms.ModelForm):
    """Create or edit an event, with its FX rates as editable rows.

    On create, `owner` is required: it becomes `Event.owner` and gets an
    owner `Participant` row, without which they couldn't open their own
    event. `base_currency` is locked after creation, and so is the rate of
    any currency an expense already uses, because changing it would make
    existing shares disagree with the recomputed amounts.
    """

    class Meta:
        model = Event
        fields = [
            "name",
            "start_date",
            "end_date",
            "base_currency",
            "notes",
            "is_archived",
        ]
        widgets = {
            "start_date": DateInputWithToday(),
            "end_date": DateInputWithToday(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "start_date": "Start date",
            "end_date": "End date",
            "base_currency": "Base currency",
            "is_archived": "Archived",
        }
        help_texts = {
            "base_currency": "Three-letter code. Every balance is shown in this "
            "currency. It can't be changed later.",
            "is_archived": "Hide this event from the event list. Nothing is deleted.",
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        event = self.instance
        if event.pk:
            self.fields["base_currency"].disabled = True
            self.fields["base_currency"].help_text = (
                "Locked after creation. Use Django admin to override."
            )
            used = set(event.expenses.values_list("original_currency", flat=True))
            initial = [
                {"currency": code, "rate": rate}
                for code, rate in sorted(event.fx_rates.items())
            ]
        else:
            del self.fields["is_archived"]
            self.fields["base_currency"].initial = DEFAULT_BASE_CURRENCY
            used, initial = set(), []
        self.fx_formset = FxRateFormSet(
            self.data or None, prefix="fx", initial=initial, locked=used
        )
        # One example is enough; the same placeholder on every row reads as data.
        for fx_form in self.fx_formset.forms[1:]:
            for field in fx_form.fields.values():
                field.widget.attrs.pop("placeholder", None)

    def clean_base_currency(self):
        return _clean_currency_code(self.cleaned_data.get("base_currency"))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date can't be before the start date.")
        base = cleaned.get("base_currency")
        if base and self.fx_formset.is_valid():
            codes = {f.cleaned_data.get("currency") for f in self.fx_formset.forms}
            if base in codes:
                raise ValidationError(
                    f"{base} is the base currency; it doesn't need an FX rate."
                )
        return cleaned

    def is_valid(self):
        """Valid only when the FX rate rows are valid too."""
        return super().is_valid() and self.fx_formset.is_valid()

    def _fx_rates(self):
        """Collect the rows into the `fx_rates` dict, keeping locked values as stored."""
        rates = {}
        for form in self.fx_formset.forms:
            currency = form.cleaned_data.get("currency")
            if not currency:
                continue
            if form.locked:
                rates[currency] = self.instance.fx_rates[currency]
            else:
                rates[currency] = format(form.cleaned_data["rate"].normalize(), "f")
        return rates

    @transaction.atomic
    def save(self):
        """Save the event; on create, also add the owner as a participant."""
        creating = self.instance.pk is None
        event = super().save(commit=False)
        event.fx_rates = self._fx_rates()
        if creating:
            event.owner = self.owner
        event.save()
        if creating:
            Participant.objects.create(
                event=event,
                user=self.owner,
                role=Participant.OWNER,
                joined_at=timezone.now(),
            )
        return event


class ExpenseForm(forms.ModelForm):
    """Log an expense and split it among selected participants.

    The form lists every participant in the event as a checkbox. In equal
    mode each share is `base_amount / N`. In itemized mode each person
    enters what they had, and the shared amount, surcharge, table charge,
    tax and tip are spread on top (`services.splitting.itemized_amounts`);
    the expense amount is the sum. Either way shares are rounded to the
    cent and the payer's share absorbs the remainder (the first person in
    the split when the payer isn't in it).
    """

    ITEM_PREFIX = "item_"
    EXTRA_FIELDS = (
        "shared_amount",
        "surcharge_percent",
        "table_charge",
        "tax_percent",
        "tip_percent",
    )

    shared_by = forms.ModelMultipleChoiceField(
        queryset=Participant.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Shared by",
        help_text="Who's in this split? At least one participant required.",
        required=False,
    )

    class Meta:
        model = Expense
        fields = [
            "description",
            "category",
            "paid_at",
            "payer",
            "split_mode",
            "original_amount",
            "original_currency",
            "shared_amount",
            "surcharge_percent",
            "table_charge",
            "tax_percent",
            "tip_percent",
            "receipt",
        ]
        widgets = {
            "paid_at": DateInputWithToday(),
            "split_mode": forms.RadioSelect,
        }
        labels = {
            "paid_at": "Date",
            "payer": "Paid by",
            "split_mode": "Split",
            "original_amount": "Amount",
            "original_currency": "Currency",
            "shared_amount": "Shared items",
            "surcharge_percent": "Surcharge %",
            "table_charge": "Table charge",
            "tax_percent": "Tax %",
            "tip_percent": "Tip %",
        }
        help_texts = {
            "original_amount": "Use a negative amount for a refund or credit. "
            "It's split the same way, so everyone's share goes down.",
            "shared_amount": "Things everyone shared, like appetizers. Split "
            "equally before the extras.",
            "surcharge_percent": "A percent added to the food before tax.",
            "table_charge": "A flat charge, split equally and taxed.",
            "tax_percent": "",
            "tip_percent": "Calculated on the total after tax.",
        }

    def __init__(self, *args, event, user=None, participants=None, **kwargs):
        """Bind the form to an event so participant choices and FX lookups work.

        `user` is required when creating a new expense (used to populate
        `created_by`) and ignored on edit. `participants` saves a query when
        the caller already has the event's participants (one per grid row).
        """
        super().__init__(*args, **kwargs)
        self.event = event
        self.user = user
        if participants is None:
            participants = list(event.participants.all())
        self.participants = participants
        for name in ("shared_by", "payer"):
            self.fields[name].queryset = event.participants.all()
            self.fields[name].label_from_instance = participant_label
        self.fields["original_amount"].required = False
        if "split_mode" in self.fields:
            self.fields["split_mode"].required = False
        self.fields["shared_by"].widget.attrs["class"] = "form-check-input"
        items = {}
        if self.instance.pk:
            shares = list(self.instance.shares.all())
            self.fields["shared_by"].initial = [s.participant_id for s in shares]
            items = {s.participant_id: s.item_amount for s in shares}
        else:
            self.fields["shared_by"].initial = [p.pk for p in self.participants]
            self.fields["original_currency"].initial = event.base_currency
            viewer = next(
                (p for p in participants if user is not None and p.user_id == user.pk),
                None,
            )
            if viewer is not None:
                self.fields["payer"].initial = viewer.pk
            # Filled in the browser: the server runs on UTC, which is
            # already tomorrow during a North American evening.
            self.fields["paid_at"].widget.attrs["data-default-today"] = ""
        if "split_mode" not in self.fields:
            return
        for participant in self.participants:
            self.fields[self._item_name(participant)] = forms.DecimalField(
                label=f"{participant_label(participant)} had",
                max_digits=12,
                decimal_places=2,
                required=False,
                initial=items.get(participant.pk),
            )

    def _item_name(self, participant):
        """Form field name for a participant's itemized amount."""
        return f"{self.ITEM_PREFIX}{participant.pk}"

    def participant_rows(self):
        """(participant, its Shared-by checkbox, its item amount field), in order.

        The item field is None on forms without the itemized mode.
        """
        checkboxes = {
            str(box.data["value"]): box for box in self["shared_by"].subwidgets
        }
        return [
            (
                p,
                checkboxes[str(p.pk)],
                self[self._item_name(p)] if self._item_name(p) in self.fields else None,
            )
            for p in self.participants
        ]

    @property
    def is_itemized(self):
        """Whether the form is showing (or was submitted in) itemized mode."""
        return self["split_mode"].value() == Expense.ITEMIZED

    def clean_split_mode(self):
        return self.cleaned_data.get("split_mode") or Expense.EQUAL

    def clean_original_currency(self):
        code = self.cleaned_data["original_currency"].upper()
        if code != self.event.base_currency and code not in self.event.fx_rates:
            raise ValidationError(
                f"No FX rate set for {code!r} on this event. "
                "Ask the event owner to add it."
            )
        return code

    def clean_receipt(self):
        """Enforce size cap and extension/content-type whitelist."""
        receipt = self.cleaned_data.get("receipt")
        if not receipt:
            return receipt
        if receipt.size > RECEIPT_MAX_BYTES:
            raise ValidationError(
                f"Receipt is {receipt.size // (1024 * 1024)} MB; max is "
                f"{RECEIPT_MAX_BYTES // (1024 * 1024)} MB."
            )
        name = (receipt.name or "").lower()
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in RECEIPT_ALLOWED_EXTENSIONS:
            raise ValidationError("Receipt must be a JPG, PNG, HEIC, or PDF file.")
        content_type = getattr(receipt, "content_type", "") or ""
        if content_type and content_type not in RECEIPT_ALLOWED_CONTENT_TYPES:
            raise ValidationError(f"Unsupported receipt content type: {content_type}.")
        return receipt

    def clean_shared_by(self):
        shared = self.cleaned_data["shared_by"]
        if not shared:
            raise ValidationError("Select at least one participant for the split.")
        return shared

    def clean(self):
        cleaned = super().clean()
        shared_by = cleaned.get("shared_by") or []
        if cleaned.get("split_mode") == Expense.ITEMIZED:
            self._clean_itemized(cleaned, shared_by)
        elif cleaned.get("original_amount") is None:
            self.add_error("original_amount", "Enter the amount.")
        return cleaned

    def _clean_itemized(self, cleaned, shared_by):
        """Check the item rows and work out the total from them."""
        included = {p.pk for p in shared_by}
        items = {}
        for participant in self.participants:
            amount = cleaned.get(self._item_name(participant))
            if participant.pk in included:
                items[participant.pk] = amount or Decimal("0")
            elif amount:
                self.add_error(
                    self._item_name(participant),
                    "Tick this person under Shared by to include them.",
                )
        if not items:
            return
        if not any(items.values()) and not cleaned.get("shared_amount"):
            raise ValidationError(
                "Enter what each person had, or a shared amount, to split by item."
            )
        self.itemized_exact = itemized_amounts(
            items, **{name: cleaned.get(name) for name in self.EXTRA_FIELDS}
        )
        cleaned["original_amount"] = sum(
            self.itemized_exact.values(), Decimal("0")
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        self.items = items

    @transaction.atomic
    def save(self, commit=True):
        """Persist the expense and (re)create one ExpenseShare per participant.

        On edit, existing shares are wiped and recreated. Reimbursed state
        is preserved for any participant who remains in the new split.
        """
        previous_reimbursed = {}
        if self.instance.pk:
            previous_reimbursed = dict(
                self.instance.shares.values_list("participant_id", "reimbursed")
            )
        expense = super().save(commit=False)
        expense.event = self.event
        if expense.split_mode == Expense.EQUAL:
            for name in self.EXTRA_FIELDS:
                setattr(expense, name, None)
        if not expense.pk and self.user is not None:
            expense.created_by = self.user
        receipt = self.cleaned_data.get("receipt")
        if receipt and hasattr(receipt, "name"):
            expense.receipt_original_filename = receipt.name
            expense.receipt_content_type = (
                getattr(receipt, "content_type", "") or "application/octet-stream"
            )
        if commit:
            expense.save()
            expense.shares.all().delete()
            self._create_shares(expense, previous_reimbursed)
        return expense

    def _create_shares(self, expense, previous_reimbursed):
        """Split `base_amount`, the payer (or first person) absorbing the cent."""
        participants = list(self.cleaned_data["shared_by"])
        ids = [p.pk for p in participants]
        if expense.split_mode == Expense.ITEMIZED:
            rate = self.event.rate_for(expense.original_currency)
            exact = {pid: self.itemized_exact[pid] * rate for pid in ids}
            items = self.items
        else:
            exact = {pid: expense.base_amount / len(ids) for pid in ids}
            items = {}
        absorber = expense.payer_id if expense.payer_id in ids else ids[0]
        amounts = allocate(expense.base_amount, exact, absorber)
        ExpenseShare.objects.bulk_create(
            ExpenseShare(
                expense=expense,
                participant_id=pid,
                share_amount=amounts[pid],
                item_amount=items.get(pid),
                reimbursed=previous_reimbursed.get(pid, False),
            )
            for pid in ids
        )


class MarkInvalidFieldsMixin:
    """For grids that render bare widgets: flag fields with errors for Bootstrap."""

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid"
                widget.attrs["aria-invalid"] = "true"


class BulkExpenseRowForm(MarkInvalidFieldsMixin, ExpenseForm):
    """One row of the "Add several" grid: an equally split expense.

    Every row of the grid offers the same choices, so the view builds
    them once and passes them in as `choices`; left to themselves, the
    model choice fields would query the database once per row. A row
    with no description and no amount is blank and is skipped.
    """

    class Meta(ExpenseForm.Meta):
        fields = [
            "paid_at",
            "description",
            "category",
            "original_amount",
            "original_currency",
            "payer",
        ]
        widgets = {"paid_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("payer", "category", "shared_by"):
            self.fields[name].choices = choices[name]
        self.fields["original_currency"] = forms.ChoiceField(
            label="Currency",
            choices=choices["currency"],
            initial=self.event.base_currency,
        )
        for name, field in self.fields.items():
            if name == "shared_by":
                continue
            css = (
                "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )
            field.widget.attrs["class"] = f"{css} form-control-sm"
            field.widget.attrs["aria-label"] = field.label

    def has_changed(self):
        """A row counts only once it has a description or an amount."""
        return bool(self["description"].value() or self["original_amount"].value())


class BaseBulkExpenseFormSet(forms.BaseFormSet):
    """The grid's rows; at least one row must be filled in."""

    def clean(self):
        if any(self.errors):
            return
        if not any(form.has_changed() for form in self.forms):
            raise ValidationError("Fill in at least one row.")

    def filled_forms(self):
        return [form for form in self.forms if form.has_changed()]


BulkExpenseFormSet = forms.formset_factory(
    BulkExpenseRowForm, formset=BaseBulkExpenseFormSet, extra=5
)


class InvitationForm(forms.Form):
    """Owner-only form to invite somebody to an event by email."""

    email = forms.EmailField(label="Email")
    display_name = forms.CharField(
        label="Display name",
        max_length=80,
        required=False,
        help_text="Shown in expenses for this event. Defaults to their first name.",
    )

    def __init__(self, *args, event, inviter, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.inviter = inviter

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        already_invited = ExpenseInvitation.objects.filter(
            event=self.event, email__iexact=email, accepted_at__isnull=True
        ).exists()
        if already_invited:
            raise ValidationError(
                "There's already a pending invitation for this email on this event."
            )
        already_member = self.event.participants.filter(
            user__email__iexact=email
        ).exists()
        if already_member:
            raise ValidationError("This person is already a participant.")
        return email

    @transaction.atomic
    def save(self):
        """Create the invitation and a placeholder Participant row."""
        email = self.cleaned_data["email"]
        display_name = self.cleaned_data["display_name"]
        invitation = ExpenseInvitation.create(
            event=self.event,
            email=email,
            inviter=self.inviter,
            display_name=display_name,
        )
        Participant.objects.get_or_create(
            event=self.event,
            invited_email=email,
            defaults={"display_name": display_name, "role": Participant.MEMBER},
        )
        return invitation


class PersonRowForm(MarkInvalidFieldsMixin, forms.Form):
    """One row of the owner's "Add people" grid.

    A name only adds someone who can pay for and share expenses without
    logging in. An email is kept on the participant, and with Invite ticked
    an invitation goes out too; accepting it links the account to this
    same row (matched on `invited_email`). A row with neither name nor
    email is blank and is skipped.
    """

    display_name = forms.CharField(label="Name", max_length=80, required=False)
    email = forms.EmailField(label="Email", required=False)
    invite = forms.BooleanField(label="Invite", required=False, initial=True)

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        # Other people's details: keep browsers and password managers from
        # offering to fill them in with the owner's own.
        self.fields["display_name"].widget.attrs.update(
            {
                "class": "form-control form-control-sm",
                "aria-label": "Name",
                "autocomplete": "off",
                "data-1p-ignore": "",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": "form-control form-control-sm",
                "aria-label": "Email",
                "autocomplete": "off",
                "data-1p-ignore": "",
            }
        )
        self.fields["invite"].widget.attrs.update(
            {"class": "form-check-input", "aria-label": "Send an invitation"}
        )

    def has_changed(self):
        """A row counts only once it has a name or an email."""
        return bool(self["display_name"].value() or self["email"].value())

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email:
            return email
        if _email_taken(self.event, email):
            raise ValidationError("Someone in this event already has this email.")
        pending = ExpenseInvitation.objects.filter(
            event=self.event, email__iexact=email, accepted_at__isnull=True
        ).exists()
        if pending:
            raise ValidationError(
                "There's already a pending invitation for this email."
            )
        return email

    @property
    def sends_invite(self):
        return bool(self.cleaned_data.get("invite") and self.cleaned_data.get("email"))


class BasePeopleFormSet(forms.BaseFormSet):
    """The "Add people" rows; at least one, and no email twice."""

    def clean(self):
        if any(self.errors):
            return
        filled = self.filled_forms()
        if not filled:
            raise ValidationError("Fill in at least one person.")
        emails = [f.cleaned_data["email"] for f in filled if f.cleaned_data["email"]]
        if len(emails) != len(set(emails)):
            raise ValidationError("Each email can only be used once.")

    def filled_forms(self):
        return [form for form in self.forms if form.has_changed()]

    @transaction.atomic
    def save(self, inviter):
        """Create the participants and invitations; return the invitations to send."""
        invitations = []
        for form in self.filled_forms():
            name, email = form.cleaned_data["display_name"], form.cleaned_data["email"]
            Participant.objects.create(
                event=form.event,
                display_name=name,
                invited_email=email,
                role=Participant.MEMBER,
            )
            if form.sends_invite:
                invitations.append(
                    ExpenseInvitation.create(
                        event=form.event,
                        email=email,
                        inviter=inviter,
                        display_name=name,
                    )
                )
        return invitations


PeopleFormSet = forms.formset_factory(PersonRowForm, formset=BasePeopleFormSet, extra=3)


class ParticipantInviteForm(InvitationForm):
    """Invite a participant who was added by name, keeping their row.

    The invitation's email is written onto the participant, and accepting
    links the account to that same row (matched on `invited_email`).
    """

    def __init__(self, *args, participant, **kwargs):
        super().__init__(*args, **kwargs)
        self.participant = participant
        del self.fields["display_name"]
        self.fields["email"].initial = participant.invited_email

    def clean_email(self):
        email = super().clean_email()
        if _email_taken(self.event, email, exclude=self.participant):
            raise ValidationError("Someone else in this event already has this email.")
        return email

    @transaction.atomic
    def save(self):
        email = self.cleaned_data["email"]
        self.participant.invited_email = email
        self.participant.save(update_fields=["invited_email", "modified_date"])
        return ExpenseInvitation.create(
            event=self.event,
            email=email,
            inviter=self.inviter,
            display_name=self.participant.display_name,
        )


def _email_taken(event, email, exclude=None):
    """True if another participant of `event` has `email` (invited or linked)."""
    others = event.participants.filter(
        Q(invited_email__iexact=email) | Q(user__email__iexact=email)
    )
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    return others.exists()


class AcceptInviteSignupForm(forms.Form):
    """Sign-up form rendered on the accept-invite page when no user exists yet.

    Email is fixed to the invitation's email (passed in by the view, not
    editable here). The form collects a username + password pair, creates
    a fresh User, and returns it so the view can `login()` and proceed.
    """

    username = forms.CharField(
        label="Username",
        max_length=150,
        help_text="Used to log in. Letters, digits and @/./+/-/_ only.",
    )
    first_name = forms.CharField(label="First name", max_length=150, required=False)
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput, strip=False
    )
    password2 = forms.CharField(
        label="Password (again)", widget=forms.PasswordInput, strip=False
    )

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        if User.objects.filter(email__iexact=self.email).exists():
            raise ValidationError(
                "This email address already has an account. "
                "Please log in instead of signing up."
            )
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords don't match.")
        if p1:
            try:
                validate_password(p1)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.email,
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data.get("first_name", ""),
        )
