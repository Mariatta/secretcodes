from django import forms

from .models import Asset, Campaign, ContentBoard, Post
from .tagging import parse_tag_names, resolve_tags


class BoardForm(forms.ModelForm):
    """Create / edit a board. Slug is assigned from the name in the view."""

    class Meta:
        model = ContentBoard
        fields = ["name", "timezone", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class CampaignForm(forms.ModelForm):
    """Create / edit a campaign.

    Tags are entered as a comma-separated string and resolved against the
    board's tag vocabulary on save (existing names reused, new ones created).
    """

    tags = forms.CharField(
        required=False,
        help_text="Comma-separated. New tags are created automatically.",
    )

    class Meta:
        model = Campaign
        fields = ["name", "event_date", "narrative_notes", "source_url"]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "narrative_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, board, **kwargs):
        super().__init__(*args, **kwargs)
        self.board = board
        if self.instance.pk:
            self.fields["tags"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def save(self, commit=True):
        campaign = super().save(commit=False)
        campaign.board = self.board
        if commit:
            campaign.save()
            names = parse_tag_names(self.cleaned_data["tags"])
            campaign.tags.set(resolve_tags(self.board, names))
        return campaign


# Fields shared by the create and edit post forms (everything except the
# channel selector, which differs: single on edit, multi on create).
_POST_SHARED_FIELDS = [
    "title",
    "scheduled_at",
    "is_all_day",
    "anchor_offset_days",
    "date_locked",
    "status",
    "body_snippet",
    "draft_url",
    "published_url",
    "assets",
    "expected_asset",
    "notes",
]
_POST_SHARED_WIDGETS = {
    # Status renders as a dot+pill toggle group (see _status_picker.html). The
    # widget is declared here, not reassigned in __init__, so the ModelForm
    # wires the field's choices onto it at construction time.
    "status": forms.RadioSelect(attrs={"class": "btn-check"}),
    "scheduled_at": forms.DateTimeInput(
        attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
    ),
    "body_snippet": forms.Textarea(attrs={"rows": 10}),
    "notes": forms.Textarea(attrs={"rows": 3}),
}


def _configure_shared_post_fields(form, campaign):
    """Apply the schedule and asset-picker tweaks common to both post forms.

    A non-event campaign uses only an absolute ``scheduled_at`` (the offset
    field is removed). An event-anchored campaign gets a ``schedule_mode``
    chooser: enter the schedule as days-from-event (``anchor_offset_days``) or
    as a specific date (``scheduled_at``); whichever you don't use is cleared in
    ``clean`` so the model computes it. ``is_all_day`` applies either way.
    """
    # Accept a full datetime or a bare date (all-day posts only need a date).
    form.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d"]
    if campaign.event_date is None:
        del form.fields["anchor_offset_days"]
        form.fields["scheduled_at"].help_text = (
            "Date and time in the board's timezone. For an all-day post a date "
            "is enough — also tick “Is all day”. Leave blank if unscheduled."
        )
    else:
        form.fields["schedule_mode"] = forms.ChoiceField(
            label="Schedule by",
            choices=[("offset", "Days from event date"), ("date", "Specific date")],
            widget=forms.RadioSelect(attrs={"class": "btn-check"}),
            initial="offset",
            required=False,
        )
        form.fields["anchor_offset_days"].help_text = (
            "Days relative to the campaign’s event date (−90 = 90 days before)."
        )
        form.fields["scheduled_at"].help_text = (
            "A specific date/time in the board's timezone. Stored as an offset "
            "from the event date, so it still moves if the event date changes."
        )
    # Scope the asset picker to the campaign's board (form-layer board isolation
    # — a cross-board asset id is rejected as an invalid choice). Archived assets
    # are excluded. Until the board has any pickable assets there's nothing to
    # pick, so hide the field rather than show a confusing empty box.
    board_assets = Asset.objects.filter(board=campaign.board).exclude(
        status=Asset.Status.ARCHIVED
    )
    if board_assets.exists():
        form.fields["assets"].queryset = board_assets
        form.fields["assets"].help_text = (
            "Attach images or files from this board's asset library."
        )
    else:
        del form.fields["assets"]


def _resolve_schedule_mode(cleaned_data):
    """For event-anchored campaigns, keep only the chosen scheduling input.

    Clearing the other one lets the model derive it: pick "offset" and the date
    is computed from it; pick "date" and the offset is derived from the date.
    A no-op for non-event campaigns (no ``schedule_mode`` field).
    """
    mode = cleaned_data.get("schedule_mode")
    if mode == "offset":
        cleaned_data["scheduled_at"] = None
    elif mode == "date":
        cleaned_data["anchor_offset_days"] = None
    return cleaned_data


class PostForm(forms.ModelForm):
    """Edit a single post. Channel is a single-select toggle group."""

    class Meta:
        model = Post
        fields = ["channel"] + _POST_SHARED_FIELDS
        widgets = {
            "channel": forms.RadioSelect(attrs={"class": "btn-check"}),
            **_POST_SHARED_WIDGETS,
        }

    def __init__(self, *args, campaign, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign
        # Drop the blank "---------" choice Django adds for a default-less field;
        # a post always has exactly one channel, so the toggle group shouldn't
        # offer an empty option.
        self.fields["channel"].choices = list(Post.CHANNEL_CHOICES)
        _configure_shared_post_fields(self, campaign)

    def clean(self):
        return _resolve_schedule_mode(super().clean())

    def save(self, commit=True):
        post = super().save(commit=False)
        post.campaign = self.campaign
        if commit:
            post.save()
            self.save_m2m()
        return post


class PostCreateForm(forms.ModelForm):
    """Create posts. Pick one or more channels — one post is created per channel.

    Each channel becomes its own ``Post`` (the model is one post per channel ×
    date), so each can be tracked and published independently. The shared body,
    schedule, and metadata are copied to every created post.
    """

    channels = forms.MultipleChoiceField(
        choices=Post.CHANNEL_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "btn-check"}),
        help_text="Pick one or more — a separate post is created for each.",
    )

    class Meta:
        model = Post
        fields = _POST_SHARED_FIELDS
        widgets = _POST_SHARED_WIDGETS

    def __init__(self, *args, campaign, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign
        _configure_shared_post_fields(self, campaign)

    def clean(self):
        return _resolve_schedule_mode(super().clean())

    def create_posts(self, created_by):
        """Create and return one Post per selected channel."""
        data = self.cleaned_data
        shared = {name: data[name] for name in _POST_SHARED_FIELDS if name in data}
        assets = shared.pop("assets", None)
        posts = []
        for channel in data["channels"]:
            post = Post(
                campaign=self.campaign,
                created_by=created_by,
                channel=channel,
                **shared,
            )
            post.save()
            if assets is not None:
                post.assets.set(assets)
            posts.append(post)
        return posts


class AssetForm(forms.ModelForm):
    """Create / edit a board asset. Status renders as a dot+pill toggle group."""

    class Meta:
        model = Asset
        fields = ["name", "kind", "file", "source_url", "caption", "status", "notes"]
        widgets = {
            "status": forms.RadioSelect(attrs={"class": "btn-check"}),
            "caption": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
