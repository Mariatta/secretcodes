"""JSON Schemas for the content_planner import/export formats.

The create-from-chat schema is the contract an agent (Claude or otherwise)
follows when producing a campaign JSON, and the same structure the import
parser checks on submit, so "what the agent was told" and "what the form
accepts" cannot drift. Channel and status enums are read from the models, so a
new channel shows up in the schema the moment it lands in code.

Regenerate the committed files in ``content_planner/schemas/`` with
``./manage.py rebuild_content_schemas`` (CI runs it with ``--check``).
"""

from pathlib import Path

from django.conf import settings

from .models import Post

SCHEMA_DIR = Path(settings.BASE_DIR) / "content_planner" / "schemas"

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _channels():
    return [value for value, _ in Post.CHANNEL_CHOICES]


def _statuses():
    return [value for value, _ in Post.Status.choices]


def build_create_from_chat_schema():
    """Schema for the create-from-chat import (one campaign + its posts).

    Lenient like the importer: unknown keys (id, slug, status, created_by,
    server-computed dates) are allowed and ignored, so an exported campaign can
    be re-imported untouched. Every imported post starts in ``drafting``.
    """
    return {
        "$schema": DRAFT,
        "$id": "schema://content/create-from-chat",
        "title": "Content planner - create campaign from chat",
        "description": (
            "Input for the create-from-chat import: one campaign and its posts. "
            "Extra keys (id, slug, status, created_by, server-computed dates) are "
            "ignored. Every imported post starts in 'drafting'."
        ),
        "type": "object",
        "required": ["campaign", "posts"],
        "properties": {
            "campaign": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "event_date": {
                        "type": ["string", "null"],
                        "format": "date",
                        "description": (
                            "ISO date (YYYY-MM-DD). When set, posts may use "
                            "anchor_offset_days to schedule relative to it."
                        ),
                    },
                    "narrative_notes": {"type": "string"},
                    "source_url": {
                        "type": "string",
                        "description": "Link to the planning chat or doc.",
                    },
                    "hashtags": {
                        "type": "string",
                        "description": (
                            "Default hashtags for this campaign's social posts, "
                            "space- or comma-separated, e.g. '#PyLadiesCon #Python'."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Board-level tags; created if new.",
                    },
                },
            },
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "channel"],
                    "properties": {
                        "title": {"type": "string", "minLength": 1},
                        "channel": {"type": "string", "enum": _channels()},
                        "scheduled_at": {
                            "type": ["string", "null"],
                            "format": "date-time",
                            "description": (
                                "ISO datetime. Used when the post is not "
                                "event-anchored. A naive value assumes the board "
                                "timezone. null = unscheduled."
                            ),
                        },
                        "anchor_offset_days": {
                            "type": ["integer", "null"],
                            "description": (
                                "Days from the campaign's event_date (negative = "
                                "before). Honored only when event_date is set."
                            ),
                        },
                        "time_of_day": {
                            "type": "string",
                            "format": "time",
                            "description": (
                                "ISO time (HH:MM), paired with anchor_offset_days."
                            ),
                        },
                        "is_all_day": {
                            "type": "boolean",
                            "description": (
                                "Defaults to true for blog/newsletter, else false."
                            ),
                        },
                        "body_snippet": {"type": "string"},
                        "expected_asset": {
                            "type": "string",
                            "description": ("Assets this post expects, one per line."),
                        },
                        "hashtags": {
                            "type": "string",
                            "description": (
                                "Extra hashtags for this post, added to the "
                                "campaign's. Used on social channels."
                            ),
                        },
                        "notes": {"type": "string"},
                    },
                },
            },
        },
    }


def build_export_schema():
    """Schema for the campaign export JSON (superset of create-from-chat)."""
    schema = {
        "$schema": DRAFT,
        "$id": "schema://content/export",
        "title": "Content planner - campaign export",
        "description": (
            "Full export shape for a campaign. A superset of create-from-chat: "
            "re-importing ignores id, slug, status, created_by and the dates."
        ),
        "type": "object",
        "required": ["campaign", "posts"],
        "properties": {
            "campaign": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "slug": {"type": "string"},
                    "name": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "event_date": {"type": ["string", "null"], "format": "date"},
                    "narrative_notes": {"type": "string"},
                    "source_url": {"type": "string"},
                    "hashtags": {"type": "string"},
                    "creation_date": {"type": "string", "format": "date-time"},
                    "modified_date": {"type": "string", "format": "date-time"},
                },
            },
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "slug": {"type": "string"},
                        "title": {"type": "string"},
                        "channel": {"type": "string", "enum": _channels()},
                        "scheduled_at": {
                            "type": ["string", "null"],
                            "format": "date-time",
                        },
                        "is_all_day": {"type": "boolean"},
                        "anchor_offset_days": {"type": ["integer", "null"]},
                        "status": {"type": "string", "enum": _statuses()},
                        "body_snippet": {"type": "string"},
                        "draft_url": {"type": "string"},
                        "published_url": {"type": "string"},
                        "expected_asset": {"type": "string"},
                        "hashtags": {"type": "string"},
                        "notes": {"type": "string"},
                        "created_by": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }
    return schema
