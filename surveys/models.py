import uuid

from django.conf import settings
from django.db import models
from django.utils.timezone import now


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


class Survey(BaseModel):
    """Top-level container. One Survey owns many Questions."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="surveys",
    )
    title = models.CharField("title", max_length=200)
    slug = models.SlugField("slug", max_length=80, unique=True)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    short_url = models.OneToOneField(
        "qrcode_manager.QRCode",
        on_delete=models.SET_NULL,
        related_name="survey",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-creation_date"]

    def __str__(self):
        return self.title


class Question(BaseModel):
    """One question on a Survey. `config` holds type-specific settings."""

    class Type(models.TextChoices):
        RATING = "rating", "Rating"
        MULTI_SELECT = "multi_select", "Multi-select"
        NPS = "nps", "NPS"
        OPEN_TEXT = "open_text", "Open text"
        YES_NO = "yes_no", "Yes / no"

    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, related_name="questions"
    )
    text = models.TextField("text")
    type = models.CharField("type", max_length=20, choices=Type.choices)
    config = models.JSONField("config", default=dict, blank=True)
    required = models.BooleanField("required", default=True)
    order = models.PositiveIntegerField("order")

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["survey", "order"],
                name="surveys_question_unique_order_per_survey",
            ),
        ]

    def __str__(self):
        return f"{self.survey.title} — Q{self.order}"


class Response(models.Model):
    """One answer to one Question.

    Anonymity is structural: no FK to user, no IP, no user-agent. Answers
    from the same fill share `submission_uuid`. Validation of `value`
    against `Question.type` lives in forms/serializers, not on the model.
    """

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="responses"
    )
    submission_uuid = models.UUIDField("submission_uuid", default=uuid.uuid4)
    value = models.JSONField("value", default=dict)
    submitted_at = models.DateTimeField("submitted_at", auto_now_add=True)
    is_flagged = models.BooleanField("is_flagged", default=False)

    class Meta:
        ordering = ["submitted_at"]
        indexes = [
            models.Index(fields=["submission_uuid"]),
            models.Index(fields=["question", "submitted_at"]),
        ]

    def __str__(self):
        return f"Response to {self.question} @ {self.submitted_at:%Y-%m-%d %H:%M}"


class Theme(BaseModel):
    """A grouping of Responses around a single concern.

    A Theme with `action_item` filled in *is* an action item — surfaces on
    the action items dashboard.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="themes")
    name = models.CharField("name", max_length=120)
    tag = models.CharField("tag", max_length=40, blank=True, default="")
    action_item = models.TextField("action_item", blank=True, default="")
    priority = models.CharField(
        "priority", max_length=20, choices=Priority.choices, default=Priority.MEDIUM
    )
    status = models.CharField(
        "status", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    responses = models.ManyToManyField(
        Response, through="ResponseTheme", related_name="themes"
    )

    class Meta:
        ordering = ["survey", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["survey", "name"],
                name="surveys_theme_unique_name_per_survey",
            ),
        ]

    def __str__(self):
        return self.name


class ResponseTheme(models.Model):
    """Through table linking a Response to a Theme.

    Carries the per-tag metadata: who tagged it, when, and whether this
    Response is the one starred as the theme's representative quote.
    """

    response = models.ForeignKey(Response, on_delete=models.CASCADE)
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)
    is_representative = models.BooleanField("is_representative", default=False)
    tagged_at = models.DateTimeField("tagged_at", auto_now_add=True)
    tagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="response_tags",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-tagged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["response", "theme"],
                name="surveys_responsetheme_unique_response_theme",
            ),
            models.UniqueConstraint(
                fields=["theme"],
                condition=models.Q(is_representative=True),
                name="surveys_responsetheme_one_representative_per_theme",
            ),
        ]

    def __str__(self):
        return f"{self.response} ↔ {self.theme}"
