"""Cross-app abstract bases.

Three things live here:

* ``BaseModel`` — timestamp mixin previously copy-pasted into every app.
* ``AbstractInvitation`` — email + key + sent_at + accepted_at pattern shared
  by ``SurveyInvitation`` and ``ExpenseInvitation``.
* ``AbstractMembership`` — the (user, joined_at) pair shared by simple
  through-tables like ``SurveyCollaborator``. Note that
  ``expenses.Participant`` deliberately does NOT inherit this — its shape
  is just different enough (nullable user, display_name, payment_info).

See ``handoff/account_handoff.md`` for the full design + migration plan.
"""

import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import now

INVITATION_KEY_LENGTH = 64


def mint_invitation_key() -> str:
    """Random URL-safe key for an invitation row, lowercased for tidiness."""
    return get_random_string(INVITATION_KEY_LENGTH).lower()


class BaseModel(models.Model):
    """Common ``creation_date`` / ``modified_date`` timestamps.

    ``modified_date`` is bumped explicitly in ``save()`` so that calls
    using ``update_fields=...`` don't accidentally skip the update.
    """

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


class AbstractInvitation(BaseModel):
    """An email invitation to join a scope. Subclasses add the scope FK.

    Subclasses must set ``EXPIRY_SETTING`` to the Django settings key
    holding their day-count (e.g. ``"SURVEYS_INVITATION_EXPIRY_DAYS"``).
    This avoids the abstract hardcoding any single app's setting name.
    """

    email = models.EmailField()
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_invitations_sent",
    )
    key = models.CharField(max_length=INVITATION_KEY_LENGTH, unique=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    EXPIRY_SETTING: str = ""

    class Meta:
        abstract = True
        ordering = ["-creation_date"]

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None

    def is_expired(self) -> bool:
        """True once ``EXPIRY_SETTING`` days have passed since send.

        Anchors to ``sent_at`` when set; falls back to ``creation_date``
        so a freshly minted row that hasn't yet been emailed still has
        a sensible expiry clock.
        """
        anchor = self.sent_at or self.creation_date
        days = getattr(settings, self.EXPIRY_SETTING)
        return anchor + datetime.timedelta(days=days) <= timezone.now()


class AbstractMembership(BaseModel):
    """User-in-a-scope through-table base.

    The ``user`` field is non-nullable here; apps that need to represent
    invited-but-not-yet-joined participants (like ``expenses.Participant``)
    shouldn't inherit this — they need their own nullable shape.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
