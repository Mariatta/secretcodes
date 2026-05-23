import datetime
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import now

INVITATION_KEY_LENGTH = 64

QUESTION_WARN_THRESHOLD = 10
QUESTION_HARD_LIMIT = 20

DESCRIPTION_MAX_LENGTH = 500


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
    description = models.TextField(
        "description", max_length=DESCRIPTION_MAX_LENGTH, blank=True, default=""
    )
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
        permissions = [
            ("access_surveys", "Can access the surveys module"),
            ("create_surveys", "Can create new surveys"),
        ]

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


class SurveyCollaborator(BaseModel):
    """A non-owner user who can edit + triage a specific survey.

    The survey's ``owner`` field is the implicit owner role — collaborators
    are additive. Cannot invite further collaborators or delete the survey.
    """

    class Role(models.TextChoices):
        COLLABORATOR = "collaborator", "Collaborator"

    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, related_name="collaborators"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="survey_collaborations",
    )
    role = models.CharField(
        "role", max_length=20, choices=Role.choices, default=Role.COLLABORATOR
    )
    joined_at = models.DateTimeField("joined_at", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["survey", "user"],
                name="surveys_collaborator_unique_user_per_survey",
            ),
        ]
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user} on {self.survey}"


class SurveyInvitation(BaseModel):
    """An email invitation to collaborate on a specific survey.

    Inviter is always the survey owner (enforced at view level). On accept,
    the recipient is granted the ``access_surveys`` permission and a
    ``SurveyCollaborator`` row is created bound to their User account.
    """

    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField("email")
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="survey_invitations_sent",
    )
    key = models.CharField("key", max_length=INVITATION_KEY_LENGTH, unique=True)
    sent_at = models.DateTimeField("sent_at", null=True, blank=True)
    accepted_at = models.DateTimeField("accepted_at", null=True, blank=True)

    class Meta:
        verbose_name = "survey invitation"
        verbose_name_plural = "survey invitations"
        ordering = ["-creation_date"]

    def __str__(self):
        return f"Invite {self.email} to {self.survey.title}"

    @classmethod
    def create(cls, *, survey, email, inviter):
        """Mint an invitation with a random url-safe key."""
        return cls.objects.create(
            survey=survey,
            email=email,
            inviter=inviter,
            key=get_random_string(INVITATION_KEY_LENGTH).lower(),
        )

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None

    def is_expired(self) -> bool:
        """True once ``SURVEYS_INVITATION_EXPIRY_DAYS`` have passed since send."""
        anchor = self.sent_at or self.creation_date
        cutoff = anchor + datetime.timedelta(
            days=settings.SURVEYS_INVITATION_EXPIRY_DAYS
        )
        return cutoff <= timezone.now()
