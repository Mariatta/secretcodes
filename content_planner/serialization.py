"""Serialize a campaign to the export JSON shape.

This is the read side of the Claude loop: a campaign's current state as JSON,
in the same schema the create-from-chat importer consumes (plus extra fields
the importer ignores — ids, statuses, timestamps, asset metadata). Datetimes
render in the board's timezone.
"""

from zoneinfo import ZoneInfo


def _iso_local(value, tz_name):
    """ISO-8601 in the board's timezone, or None."""
    if value is None:
        return None
    return value.astimezone(ZoneInfo(tz_name)).isoformat()


def campaign_to_export_dict(campaign):
    board = campaign.board
    tz = board.timezone
    posts = list(campaign.posts.select_related("created_by").prefetch_related("assets"))

    assets = {}
    for post in posts:
        for asset in post.assets.all():
            assets[asset.pk] = asset

    return {
        "campaign": {
            "id": campaign.pk,
            "slug": campaign.slug,
            "name": campaign.name,
            "tags": list(campaign.tags.values_list("name", flat=True)),
            "event_date": (
                campaign.event_date.isoformat() if campaign.event_date else None
            ),
            "narrative_notes": campaign.narrative_notes,
            "source_url": campaign.source_url,
            "hashtags": campaign.hashtags,
            "creation_date": campaign.creation_date.isoformat(),
            "modified_date": campaign.modified_date.isoformat(),
        },
        "posts": [
            {
                "id": post.pk,
                "slug": post.slug,
                "title": post.title,
                "channel": post.channel,
                "scheduled_at": _iso_local(post.scheduled_at, tz),
                "is_all_day": post.is_all_day,
                "anchor_offset_days": post.anchor_offset_days,
                "status": post.status,
                "body_snippet": post.body_snippet,
                "draft_url": post.draft_url,
                "published_url": post.published_url,
                "expected_asset": post.expected_asset,
                "hashtags": post.hashtags,
                "notes": post.notes,
                "created_by": (post.created_by.username if post.created_by else None),
            }
            for post in posts
        ],
        "assets": [
            {
                "id": asset.pk,
                "name": asset.name,
                "kind": asset.kind,
                "caption": asset.caption,
                "status": asset.status,
                "source_url": asset.source_url,
                "file_url": asset.file.url if asset.file else "",
            }
            for asset in assets.values()
        ],
    }
