import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import now

from .storage import EncryptedFileSystemStorage

CURRENCY_CODE_LENGTH = 3
MONEY_DECIMAL_PLACES = 2
MONEY_MAX_DIGITS = 12
INVITATION_KEY_LENGTH = 64
RECEIPT_MAX_BYTES = 10 * 1024 * 1024
RECEIPT_ALLOWED_EXTENSIONS = ("jpg", "jpeg", "png", "heic", "pdf")
RECEIPT_ALLOWED_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/heic",
    "application/pdf",
)


def _receipt_upload_to(instance, filename):
    """Randomized path: receipts/<event_id>/<uuid>.<ext>.

    Originates the new disk filename — never trusts the user-supplied
    name. The original filename is stored separately on the model so
    we can reuse it on download.
    """
    extension = PurePosixPath(filename).suffix.lower().lstrip(".") or "bin"
    return f"receipts/{instance.event_id}/{uuid.uuid4().hex}.{extension}"


class BaseModel(models.Model):
    """Mirror of availability.models.BaseModel — common timestamp fields."""

    creation_date = models.DateTimeField(
        "creation_date", editable=False, auto_now_add=True
    )
    modified_date = models.DateTimeField("modified_date", editable=False, auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.modified_date = now()
        if "update_fields" in kwargs and "modified_date" not in kwargs["update_fields"]:
            kwargs["update_fields"].append("modified_date")
        super().save(*args, **kwargs)


class Category(BaseModel):
    """Globally shared expense category. Admin-managed."""

    name = models.CharField("name", max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Event(BaseModel):
    """A trip or gathering with shared expenses."""

    name = models.CharField("name", max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_events",
    )
    start_date = models.DateField("start_date", null=True, blank=True)
    end_date = models.DateField("end_date", null=True, blank=True)
    base_currency = models.CharField(
        "base_currency",
        max_length=CURRENCY_CODE_LENGTH,
        help_text="ISO 4217 code, e.g. USD. Locked at creation; admin override only.",
    )
    fx_rates = models.JSONField(
        "fx_rates",
        default=dict,
        blank=True,
        help_text='Map of currency code to multiplier into base, e.g. {"JPY": 0.0067}.',
    )
    notes = models.TextField("notes", blank=True, default="")
    is_archived = models.BooleanField("is_archived", default=False)

    class Meta:
        ordering = ["-start_date", "-creation_date"]
        permissions = [
            ("access_expenses", "Can access the expenses module"),
        ]

    def __str__(self):
        return self.name

    def rate_for(self, currency_code):
        """Return Decimal rate for converting `currency_code` into base.

        Base currency is implicitly 1.0. Raises ValidationError if the
        requested currency isn't in fx_rates.
        """
        if currency_code == self.base_currency:
            return Decimal("1")
        if currency_code not in self.fx_rates:
            raise ValidationError(
                f"No FX rate set for {currency_code!r} on event {self.name!r}. "
                "Ask the event owner to add it."
            )
        return Decimal(str(self.fx_rates[currency_code]))


class Participant(BaseModel):
    """A user's membership in an event.

    `user` is nullable to allow pre-acceptance Participant rows (the
    invitation flow in Phase 3 will fill this in on accept). For Phase 1,
    participants are added manually via the admin and `user` is always set.
    """

    OWNER = "owner"
    MEMBER = "member"
    ROLE_CHOICES = [(OWNER, "Owner"), (MEMBER, "Member")]

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="event_participations",
    )
    invited_email = models.EmailField("invited_email", blank=True, default="")
    display_name = models.CharField("display_name", max_length=80, blank=True)
    role = models.CharField("role", max_length=10, choices=ROLE_CHOICES, default=MEMBER)
    joined_at = models.DateTimeField("joined_at", null=True, blank=True)
    payment_info = models.TextField(
        "payment_info",
        blank=True,
        default="",
        help_text=(
            "How others can pay you back — free text. e.g. 'paypal.me/alice', "
            "'e-transfer to alice@example.com', wire details, etc. Shown to "
            "anyone who owes this participant."
        ),
    )

    class Meta:
        unique_together = [("event", "user")]
        ordering = ["display_name", "id"]

    def __str__(self):
        return f"{self.display_name or self.invited_email} @ {self.event.name}"

    def save(self, *args, **kwargs):
        """Default display_name to user.first_name (or username) when blank."""
        if not self.display_name and self.user_id:
            self.display_name = self.user.first_name or self.user.get_username()
        super().save(*args, **kwargs)


class Expense(BaseModel):
    """A single expense in an event.

    Phase 1 scope: paid-only expenses. The estimated_amount and receipt
    fields ship in Phase 2; the three-state model (planned / quoted+paid /
    paid-only) is documented in expenses-design.md.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="expenses")
    description = models.CharField("description", max_length=200)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="expenses"
    )
    original_amount = models.DecimalField(
        "original_amount",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
    )
    original_currency = models.CharField(
        "original_currency", max_length=CURRENCY_CODE_LENGTH
    )
    base_amount = models.DecimalField(
        "base_amount",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        help_text="Computed at save: original_amount * event.fx_rates[currency].",
    )
    payer = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="expenses_paid",
    )
    paid_at = models.DateField("paid_at")
    receipt = models.FileField(
        "receipt",
        upload_to=_receipt_upload_to,
        storage=EncryptedFileSystemStorage(),
        null=True,
        blank=True,
        help_text="Encrypted at rest. Max 10 MB; jpg, png, heic, pdf.",
    )
    receipt_original_filename = models.CharField(
        "receipt_original_filename", max_length=255, blank=True, default=""
    )
    receipt_content_type = models.CharField(
        "receipt_content_type", max_length=64, blank=True, default=""
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expenses_created",
        help_text="User who logged this expense. Only this user (or a superuser) can delete.",
    )

    class Meta:
        ordering = ["-paid_at", "-creation_date"]

    def __str__(self):
        return f"{self.description} ({self.original_amount} {self.original_currency})"

    def save(self, *args, **kwargs):
        """Compute base_amount from event fx_rates before persisting."""
        rate = self.event.rate_for(self.original_currency)
        raw = Decimal(self.original_amount) * rate
        self.base_amount = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class ExpenseInvitation(BaseModel):
    """An email invitation to join a specific event.

    Inviter is always the event owner (enforced at view level). On accept
    the recipient is added to the `expenses_users` group and the matching
    `Participant` row (created at invite-time with a null `user`) is
    bound to their User account.
    """

    event = models.ForeignKey(
        "Event", on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField("email")
    display_name = models.CharField("display_name", max_length=80, blank=True)
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="expense_invitations_sent",
    )
    key = models.CharField("key", max_length=INVITATION_KEY_LENGTH, unique=True)
    sent_at = models.DateTimeField("sent_at", null=True, blank=True)
    accepted_at = models.DateTimeField("accepted_at", null=True, blank=True)

    class Meta:
        verbose_name = "expense invitation"
        verbose_name_plural = "expense invitations"
        ordering = ["-creation_date"]

    def __str__(self):
        return f"Invite {self.email} to {self.event.name}"

    @classmethod
    def create(cls, *, event, email, inviter, display_name=""):
        """Mint an invitation with a random url-safe key."""
        return cls.objects.create(
            event=event,
            email=email,
            inviter=inviter,
            display_name=display_name,
            key=get_random_string(INVITATION_KEY_LENGTH).lower(),
        )

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None

    def is_expired(self) -> bool:
        """True once `EXPENSES_INVITATION_EXPIRY_DAYS` have passed since send."""
        anchor = self.sent_at or self.creation_date
        cutoff = anchor + datetime.timedelta(
            days=settings.EXPENSES_INVITATION_EXPIRY_DAYS
        )
        return cutoff <= timezone.now()


class ExpenseShare(BaseModel):
    """One participant's slice of an expense, in event base currency."""

    expense = models.ForeignKey(
        Expense, on_delete=models.CASCADE, related_name="shares"
    )
    participant = models.ForeignKey(
        Participant, on_delete=models.PROTECT, related_name="shares"
    )
    share_amount = models.DecimalField(
        "share_amount",
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
    )
    reimbursed = models.BooleanField("reimbursed", default=False)

    class Meta:
        unique_together = [("expense", "participant")]
        ordering = ["participant__display_name"]

    def __str__(self):
        return f"{self.participant} owes {self.share_amount} on {self.expense}"
