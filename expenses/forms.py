from decimal import ROUND_HALF_UP, Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

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

User = get_user_model()


class EventForm(forms.ModelForm):
    """Create / edit an event. base_currency is locked after creation."""

    class Meta:
        model = Event
        fields = [
            "name",
            "start_date",
            "end_date",
            "base_currency",
            "fx_rates",
            "notes",
            "is_archived",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "fx_rates": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["base_currency"].disabled = True
            self.fields["base_currency"].help_text = (
                "Locked after creation. Use Django admin to override."
            )


class ExpenseForm(forms.ModelForm):
    """Log an expense and split it equally among selected participants.

    The form lists every participant in the event as a checkbox. On save,
    `share_amount = round(base_amount / N, 2)` and any rounding remainder
    is absorbed by the payer's share.
    """

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
            "original_amount",
            "original_currency",
            "payer",
            "paid_at",
            "receipt",
        ]
        widgets = {"paid_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, event, user=None, **kwargs):
        """Bind the form to an event so participant choices and FX lookups work.

        `user` is required when creating a new expense (used to populate
        `created_by`) and ignored on edit.
        """
        super().__init__(*args, **kwargs)
        self.event = event
        self.user = user
        participants = event.participants.all()
        self.fields["shared_by"].queryset = participants
        self.fields["payer"].queryset = participants
        if self.instance.pk:
            self.fields["shared_by"].initial = list(
                self.instance.shares.values_list("participant_id", flat=True)
            )
        else:
            self.fields["shared_by"].initial = list(participants)
            self.fields["original_currency"].initial = event.base_currency

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

    def _create_shares(self, expense, previous_reimbursed=None):
        """Equal split with payer absorbing the rounding remainder."""
        previous_reimbursed = previous_reimbursed or {}
        participants = list(self.cleaned_data["shared_by"])
        n = len(participants)
        per_person = (expense.base_amount / n).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        remainder = expense.base_amount - per_person * n

        shares = []
        for participant in participants:
            amount = per_person
            if participant.pk == expense.payer_id:
                amount = per_person + remainder
            shares.append(
                ExpenseShare(
                    expense=expense,
                    participant=participant,
                    share_amount=amount,
                    reimbursed=previous_reimbursed.get(participant.pk, False),
                )
            )
        if expense.payer not in participants:
            shares = self._reapply_remainder_to_first(shares, remainder, per_person)
        ExpenseShare.objects.bulk_create(shares)

    @staticmethod
    def _reapply_remainder_to_first(shares, remainder, per_person):
        """If the payer isn't in the split, the first participant absorbs the cent."""
        if not shares or remainder == 0:
            return shares
        shares[0].share_amount = per_person + remainder
        return shares


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
