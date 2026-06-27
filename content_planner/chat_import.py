"""Create-from-chat import: turn pasted JSON into a campaign + posts.

The write side of the Claude loop. Mirrors the export schema but deliberately
asymmetric: ids and statuses in the JSON are ignored (every post starts
DRAFTING), and only the planning fields are honored. The whole import runs in
one transaction — any bad post aborts the lot.
"""

import datetime
import json
from zoneinfo import ZoneInfo

from django.db import transaction

from .models import Campaign, Post
from .scheduling import compute_scheduled_at
from .tagging import resolve_tags

VALID_CHANNELS = {value for value, _ in Post.CHANNEL_CHOICES}
ALL_DAY_DEFAULT_CHANNELS = {"blog", "newsletter"}


class ChatImportError(ValueError):
    """A user-facing problem with the pasted JSON."""


def parse_chat_payload(raw):
    """Parse and shape-check the pasted JSON. Raises ChatImportError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatImportError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ChatImportError("Top-level JSON must be an object.")
    campaign = data.get("campaign")
    if not isinstance(campaign, dict) or not campaign.get("name"):
        raise ChatImportError("Missing campaign.name.")
    if not isinstance(data.get("posts"), list):
        raise ChatImportError("Missing posts list.")
    return data


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ChatImportError(f"Invalid event_date '{value}'.") from exc


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.time.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ChatImportError(f"Invalid time_of_day '{value}'.") from exc


def _parse_datetime(value, tz_name):
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ChatImportError(f"Invalid scheduled_at '{value}'.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed


def _build_post(campaign, board, data):
    title = data.get("title")
    channel = data.get("channel")
    if not title:
        raise ChatImportError("Each post needs a title.")
    if channel not in VALID_CHANNELS:
        raise ChatImportError(f"Unknown channel '{channel}' on post '{title}'.")

    is_all_day = data.get("is_all_day")
    if is_all_day is None:
        is_all_day = channel in ALL_DAY_DEFAULT_CHANNELS

    anchor = data.get("anchor_offset_days")
    scheduled_at = None
    if campaign.event_date is not None and anchor is not None:
        scheduled_at = compute_scheduled_at(
            event_date=campaign.event_date,
            offset_days=anchor,
            time_of_day=_parse_time(data.get("time_of_day")),
            tz_name=board.timezone,
        )
    elif data.get("scheduled_at"):
        scheduled_at = _parse_datetime(data["scheduled_at"], board.timezone)

    return Post(
        campaign=campaign,
        title=title,
        channel=channel,
        scheduled_at=scheduled_at,
        anchor_offset_days=anchor if campaign.event_date is not None else None,
        is_all_day=bool(is_all_day),
        status=Post.Status.DRAFTING,
        body_snippet=data.get("body_snippet", "") or "",
        expected_asset=data.get("expected_asset", "") or "",
        hashtags=data.get("hashtags", "") or "",
        notes=data.get("notes", "") or "",
    )


@transaction.atomic
def create_campaign_from_payload(board, data, user):
    """Create the campaign + posts from validated payload data."""
    campaign_data = data["campaign"]
    campaign = Campaign.objects.create(
        board=board,
        name=campaign_data["name"],
        narrative_notes=campaign_data.get("narrative_notes", "") or "",
        source_url=campaign_data.get("source_url", "") or "",
        hashtags=campaign_data.get("hashtags", "") or "",
        event_date=_parse_date(campaign_data.get("event_date")),
    )
    tag_names = [str(name) for name in campaign_data.get("tags") or []]
    campaign.tags.set(resolve_tags(board, tag_names))

    for post_data in data["posts"]:
        post = _build_post(campaign, board, post_data)
        post.created_by = user
        post.save()
    return campaign
