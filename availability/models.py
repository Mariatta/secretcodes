from django.db import models
from django.utils.timezone import now
from solo.models import SingletonModel
from timezone_field import TimeZoneField

from .encryption import EncryptedTextField


class BaseModel(models.Model):
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


def _default_business_hours():
    return {d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}


def _default_extended_hours():
    return {
        d: [["08:00", "09:00"], ["17:00", "19:00"]]
        for d in ("mon", "tue", "wed", "thu", "fri")
    }


class GoogleAccount(BaseModel):
    label = models.CharField("label", max_length=50)
    email = models.EmailField("email", unique=True)
    refresh_token = EncryptedTextField("refresh_token", blank=True, default="")
    scopes_granted = models.JSONField("scopes_granted", default=list)

    def __str__(self):
        return f"{self.label} <{self.email}>"


class TrackedCalendar(BaseModel):
    account = models.ForeignKey(
        GoogleAccount,
        on_delete=models.CASCADE,
        related_name="tracked_calendars",
    )
    google_calendar_id = models.CharField("google_calendar_id", max_length=255)
    display_label = models.CharField("display_label", max_length=100)
    is_active = models.BooleanField("is_active", default=True)

    class Meta:
        unique_together = ("account", "google_calendar_id")

    def __str__(self):
        return self.display_label


class AvailabilityProfile(SingletonModel):
    timezone = TimeZoneField("timezone", default="America/Vancouver", use_pytz=False)
    business_hours = models.JSONField("business_hours", default=_default_business_hours)
    extended_hours = models.JSONField("extended_hours", default=_default_extended_hours)
    default_slot_minutes = models.PositiveIntegerField(
        "default_slot_minutes", default=30
    )
    min_notice_hours = models.PositiveIntegerField("min_notice_hours", default=12)
    max_horizon_days = models.PositiveIntegerField("max_horizon_days", default=21)
    extended_reveal_threshold = models.PositiveIntegerField(
        "extended_reveal_threshold", default=4
    )
    meeting_buffer_minutes = models.PositiveIntegerField(
        "meeting_buffer_minutes",
        default=30,
        help_text=(
            "Padding applied before and after every busy block when computing "
            "free slots. 30 minutes by default."
        ),
    )
    creation_date = models.DateTimeField(
        "creation_date", editable=False, auto_now_add=True
    )
    modified_date = models.DateTimeField("modified_date", editable=False, auto_now=True)

    def __str__(self):
        return f"AvailabilityProfile ({self.timezone})"
