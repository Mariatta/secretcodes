import os
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core.encryption import EncryptedTextField
from core.models import AbstractInvitation, AbstractMembership, BaseModel

from .hashtags import merge_hashtags
from .scheduling import compute_scheduled_at, local_date, local_time_of_day
from .slugs import generate_unique_slug

# Slugs that would collide with the content_planner URL structure and so may
# not be used as a board slug. Validated when a board's slug is generated.
RESERVED_BOARD_SLUGS = frozenset(
    {
        "all",
        "new",
        "boards",
        "schedule",
        "assets",
        "campaigns",
        "publishing",
        "c",
        "mcp",
        "admin",
        "api",
        "accounts",
    }
)


class ContentBoard(BaseModel):
    """The board. One per personal-or-community context."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_content_boards",
    )
    description = models.TextField(blank=True, default="")
    timezone = models.CharField(max_length=64, default="America/Vancouver")
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("access_content_planner", "Can access the content planner module"),
        ]

    def __str__(self):
        return self.name

    def assign_slug(self):
        """Set a unique, non-reserved slug from ``name``.

        Board slugs are stable (set once, not regenerated on rename) because
        they appear in shared-within-the-app URLs. Uniqueness is global across
        boards; reserved strings that would clash with the URL structure are
        skipped with a numeric suffix.
        """
        siblings = ContentBoard.objects.all()
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        self.slug = generate_unique_slug(
            value=self.name,
            max_length=ContentBoard._meta.get_field("slug").max_length,
            queryset=siblings,
            reserved=RESERVED_BOARD_SLUGS,
        )


class ContentCollaborator(AbstractMembership):
    """A user invited onto a board.

    ``role`` is a forward-looking seam: v1 is flat (every collaborator can do
    anything except invite others or delete the board), so the field carries a
    single default value and the permission helpers ignore it. Adding tiers
    later (viewer / approver / ...) needs no data backfill.
    """

    class Role(models.TextChoices):
        EDITOR = "editor", "Editor"

    board = models.ForeignKey(
        ContentBoard, on_delete=models.CASCADE, related_name="collaborators"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EDITOR)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["board", "user"],
                name="content_collaborator_unique_user_per_board",
            ),
        ]

    def __str__(self):
        return f"{self.user} on {self.board}"


class ContentInvitation(AbstractInvitation):
    EXPIRY_SETTING = "CONTENT_INVITATION_EXPIRY_DAYS"

    board = models.ForeignKey(
        ContentBoard, on_delete=models.CASCADE, related_name="invitations"
    )

    class Meta(AbstractInvitation.Meta):
        verbose_name = "content invitation"
        verbose_name_plural = "content invitations"

    def __str__(self):
        return f"Invite {self.email} to {self.board}"


class Tag(BaseModel):
    """Per-board tag for grouping campaigns."""

    board = models.ForeignKey(
        ContentBoard, on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=40)

    class Meta:
        constraints = [
            # Case-insensitive uniqueness per board via functional index.
            models.UniqueConstraint(
                Lower("name"),
                "board",
                name="content_tag_unique_lower_name_per_board",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)


class Campaign(BaseModel):
    board = models.ForeignKey(
        ContentBoard, on_delete=models.CASCADE, related_name="campaigns"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, blank=True)
    narrative_notes = models.TextField(blank=True, default="")
    source_url = models.URLField(
        blank=True,
        default="",
        help_text="Link to the Claude chat or doc where this was planned.",
    )
    tags = models.ManyToManyField("Tag", related_name="campaigns", blank=True)
    hashtags = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Default hashtags for this campaign's social posts, e.g. "
            "“#PyLadiesCon #Python”. Appended when you copy a social post."
        ),
    )
    event_date = models.DateField(
        null=True,
        blank=True,
        help_text="If set, this campaign is event-anchored.",
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["board", "slug"],
                name="content_campaign_unique_slug_per_board",
            ),
        ]
        ordering = ["-creation_date"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self._sync_slug()
        old_event_date = None
        if self.pk:
            old_event_date = (
                Campaign.objects.filter(pk=self.pk)
                .values_list("event_date", flat=True)
                .first()
            )
        super().save(*args, **kwargs)
        if self.event_date != old_event_date:
            self._recompute_anchored_posts()

    def _sync_slug(self):
        """Regenerate the slug from ``name``, skipping if the name is unchanged."""
        if self.pk:
            old_name = (
                Campaign.objects.filter(pk=self.pk)
                .values_list("name", flat=True)
                .first()
            )
            if old_name == self.name and self.slug:
                return
        siblings = Campaign.objects.filter(board=self.board)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        self.slug = generate_unique_slug(
            value=self.name,
            max_length=Campaign._meta.get_field("slug").max_length,
            queryset=siblings,
        )

    def _recompute_anchored_posts(self):
        """Re-derive ``scheduled_at`` for anchored, unlocked posts after an
        ``event_date`` change. Time-of-day is preserved; locked posts skipped.
        """
        anchored = self.posts.filter(
            anchor_offset_days__isnull=False, date_locked=False
        )
        for post in anchored:
            post.save()


class Asset(BaseModel):
    KIND_CHOICES = [
        ("image", "Image"),
        ("graphic", "Graphic"),
        ("video", "Video"),
        ("quote_card", "Quote card"),
        ("attachment", "Attachment"),
        ("other", "Other"),
    ]

    class Status(models.TextChoices):
        DRAFTING = "drafting", "Drafting"
        READY = "ready", "Ready"
        UPLOADED = "uploaded", "Uploaded"
        ARCHIVED = "archived", "Archived"

    board = models.ForeignKey(
        ContentBoard, on_delete=models.CASCADE, related_name="assets"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="image")
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="content_planner/assets/", blank=True, null=True)
    source_url = models.URLField(blank=True, default="")
    caption = models.TextField(
        blank=True,
        default="",
        help_text="Alt text / caption.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFTING
    )
    notes = models.TextField(blank=True, default="")

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
    VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".ogg", ".m4v"}

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def media_url(self):
        """The asset's displayable URL — uploaded file, else the source URL."""
        if self.file:
            return self.file.url
        return self.source_url or ""

    @property
    def _media_extension(self):
        reference = self.file.name if self.file else (self.source_url or "")
        return os.path.splitext(urlparse(reference).path)[1].lower()

    @property
    def is_image(self):
        """True if the asset points at an image (by file/URL extension)."""
        return bool(self.media_url) and self._media_extension in self.IMAGE_EXTENSIONS

    @property
    def is_video(self):
        """True if the asset points at a video (by file/URL extension)."""
        return bool(self.media_url) and self._media_extension in self.VIDEO_EXTENSIONS


class Post(BaseModel):
    CHANNEL_CHOICES = [
        ("blog", "Blog"),
        ("mastodon", "Mastodon"),
        ("bluesky", "Bluesky"),
        ("linkedin", "LinkedIn"),
        ("x", "X / Twitter"),
        ("instagram", "Instagram"),
        ("newsletter", "Newsletter"),
        ("podcast", "Podcast"),
        ("talk", "Talk"),
        ("other", "Other"),
    ]

    # Channels where appending hashtags to the copy text makes sense.
    SOCIAL_CHANNELS = {"mastodon", "bluesky", "linkedin", "x", "instagram"}

    class Status(models.TextChoices):
        DRAFTING = "drafting", "Drafting"
        READY = "ready", "Ready"
        UPLOADED = "uploaded", "Uploaded"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
        CANCELLED = "cancelled", "Cancelled"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="posts"
    )
    slug = models.SlugField(max_length=120, blank=True)
    title = models.CharField(max_length=200, help_text="Internal label.")
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    is_all_day = models.BooleanField(
        default=False,
        help_text=(
            "When true, time component is informational only; UI shows date only."
        ),
    )
    anchor_offset_days = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Days relative to campaign.event_date. Set only for "
            "event-anchored campaigns."
        ),
    )
    date_locked = models.BooleanField(
        default=False,
        help_text="If true, this post is exempt from bulk-shift operations.",
    )
    body_snippet = models.TextField(
        blank=True,
        default="",
        help_text="Full body for social posts; subject + preview for blog/newsletter.",
    )
    draft_url = models.URLField(
        blank=True,
        default="",
        help_text=(
            "Link to the canonical draft elsewhere (GitHub repo, email service, etc.)."
        ),
    )
    published_url = models.URLField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFTING
    )
    assets = models.ManyToManyField(Asset, related_name="posts", blank=True)
    expected_asset = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Assets this post needs, one per line (e.g. “hero image”, "
            "“square graphic”). Flagged as missing until that many assets are "
            "attached. Leave blank if none."
        ),
    )
    hashtags = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Extra hashtags for this post, added to the campaign's defaults. "
            "Appended when you copy a social post."
        ),
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="content_posts_created",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "slug"],
                name="content_post_unique_slug_per_campaign",
            ),
        ]
        ordering = ["scheduled_at"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        """True if the scheduled date has passed and the post isn't done.

        Mirrors the daily overview's Overdue rule: scheduled before today's
        start in the board's timezone, excluding the terminal statuses.
        """
        if self.scheduled_at is None:
            return False
        if self.status in {
            self.Status.PUBLISHED,
            self.Status.ARCHIVED,
            self.Status.CANCELLED,
        }:
            return False
        tz_name = self.campaign.board.timezone
        return local_date(self.scheduled_at, tz_name) < local_date(
            timezone.now(), tz_name
        )

    @property
    def expected_asset_list(self):
        """The expected-asset briefs as a cleaned list (one per line)."""
        return [
            line.strip() for line in self.expected_asset.splitlines() if line.strip()
        ]

    @property
    def attached_asset_count(self):
        """How many assets are attached (uses the prefetch cache when present)."""
        return len(self.assets.all())

    @property
    def is_missing_asset(self):
        """True if fewer assets are attached than the post expects."""
        return len(self.expected_asset_list) > self.attached_asset_count

    @property
    def hashtag_list(self):
        """Effective hashtags: campaign defaults plus this post's, de-duped."""
        return merge_hashtags(self.campaign.hashtags, self.hashtags)

    @property
    def copy_text(self):
        """Body for pasting — hashtags appended on social channels."""
        if self.channel in self.SOCIAL_CHANNELS and self.hashtag_list:
            tags = " ".join(self.hashtag_list)
            return f"{self.body_snippet}\n\n{tags}" if self.body_snippet else tags
        return self.body_snippet

    def save(self, *args, **kwargs):
        self._sync_slug()
        self._apply_anchoring()
        super().save(*args, **kwargs)

    def _sync_slug(self):
        """Regenerate the slug from ``title``, skipping if the title is unchanged."""
        if self.pk:
            old_title = (
                Post.objects.filter(pk=self.pk).values_list("title", flat=True).first()
            )
            if old_title == self.title and self.slug:
                return
        siblings = Post.objects.filter(campaign=self.campaign)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        self.slug = generate_unique_slug(
            value=self.title,
            max_length=Post._meta.get_field("slug").max_length,
            queryset=siblings,
        )

    def _apply_anchoring(self):
        """Keep ``scheduled_at`` and ``anchor_offset_days`` consistent for
        event-anchored campaigns.

        If an offset is set, it drives ``scheduled_at`` (preserving the current
        time-of-day, or defaulting to 09:00). If only ``scheduled_at`` is set,
        the offset is derived from it. Non-anchored campaigns are left alone.
        """
        event_date = self.campaign.event_date
        if event_date is None:
            return
        tz_name = self.campaign.board.timezone
        if self.anchor_offset_days is not None:
            time_of_day = (
                local_time_of_day(self.scheduled_at, tz_name)
                if self.scheduled_at
                else None
            )
            self.scheduled_at = compute_scheduled_at(
                event_date=event_date,
                offset_days=self.anchor_offset_days,
                time_of_day=time_of_day,
                tz_name=tz_name,
            )
        elif self.scheduled_at is not None:
            self.anchor_offset_days = (
                local_date(self.scheduled_at, tz_name) - event_date
            ).days


# --------------------------------------------------------------- publishing
#
# Delivery. A Post is content; a Publication is one attempt to deliver that
# content to one account. The split is deliberate: a post approved once may go
# to four platforms and succeed on three. See handoff/social-publishing.md.


class Platform(models.TextChoices):
    BLUESKY = "bluesky", "Bluesky"
    MASTODON = "mastodon", "Mastodon"
    INSTAGRAM = "instagram", "Instagram"
    LINKEDIN = "linkedin", "LinkedIn"  # Phase 2, reserved


class PublishingAccount(BaseModel):
    """A connected account we can publish to.

    Named for what it does rather than "social account": if allauth's
    socialaccount app is ever enabled for login, its ``SocialAccount`` is a
    login identity carrying login scopes, and confusing the two would be an
    easy way to try publishing with a token that cannot.

    Credentials are Fernet-encrypted at rest and never rendered: not in the
    UI, not in logs, not in ``__str__``, and this model is deliberately not
    registered in the admin.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        NEEDS_REAUTH = "needs_reauth", "Needs reconnecting"
        REVOKED = "revoked", "Revoked"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="publishing_accounts",
    )
    platform = models.CharField(max_length=32, choices=Platform.choices)

    remote_id = models.CharField(
        max_length=255,
        help_text="Stable remote identity: did:plc:… / account id / ig-user-id.",
    )
    handle = models.CharField(
        max_length=255, help_text="Display only. Handles change; remote_id does not."
    )
    instance_url = models.URLField(
        blank=True, default="", help_text="Mastodon host, or Bluesky PDS."
    )

    access_token = EncryptedTextField(blank=True, default="")
    refresh_token = EncryptedTextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.ACTIVE
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Cached platform facts: instance char limit, IG page id, etc.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "platform", "remote_id"],
                name="uniq_publishing_account",
            )
        ]
        ordering = ["platform", "handle"]

    def __str__(self):
        return f"{self.handle} ({self.get_platform_display()})"


class MastodonApp(BaseModel):
    """Per-instance client registration.

    Mastodon requires registering the app with each instance separately, so
    this is a table rather than a setting.
    """

    instance_host = models.CharField(max_length=255, unique=True)
    client_id = models.CharField(max_length=255)
    client_secret = EncryptedTextField()

    class Meta:
        ordering = ["instance_host"]

    def __str__(self):
        return self.instance_host


class Publication(BaseModel):
    """One post, one account, one delivery."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CLAIMED = "claimed", "Claimed"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"
        CANCELLED = "cancelled", "Cancelled"

    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="publications"
    )
    account = models.ForeignKey(PublishingAccount, on_delete=models.PROTECT)

    scheduled_for = models.DateTimeField(db_index=True, help_text="UTC.")
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.PENDING, db_index=True
    )

    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    remote_id = models.CharField(max_length=512, blank=True, default="")
    remote_url = models.URLField(blank=True, default="")

    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set after a transient failure; the dispatcher skips the row until then.",
    )
    last_error = models.TextField(blank=True, default="")
    blockers = models.JSONField(default=list, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Connector scratch space, e.g. an Instagram container id.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["post", "account"],
                condition=models.Q(state="sent"),
                name="one_success_per_target",
            )
        ]
        indexes = [models.Index(fields=["state", "scheduled_for"])]
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"{self.post.title} → {self.account.handle}"

    @property
    def blocker_messages(self):
        """Human-readable blocker reasons, for the queue UI."""
        return [b["message"] for b in self.blockers]
