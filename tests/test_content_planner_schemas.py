"""Generated JSON Schemas + the rebuild_content_schemas management command."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from jsonschema import Draft202012Validator

from content_planner import schemas
from content_planner.models import Post


def _channel_enum(schema):
    return schema["properties"]["posts"]["items"]["properties"]["channel"]["enum"]


def test_create_from_chat_channel_enum_tracks_model():
    assert _channel_enum(schemas.build_create_from_chat_schema()) == [
        value for value, _ in Post.CHANNEL_CHOICES
    ]


def test_export_schema_status_enum_tracks_model():
    enum = schemas.build_export_schema()["properties"]["posts"]["items"]["properties"][
        "status"
    ]["enum"]
    assert enum == [value for value, _ in Post.Status.choices]


def test_committed_schemas_match_models():
    """Mirrors the CI guard: committed files must equal freshly generated."""
    call_command("rebuild_content_schemas", "--check")


def test_rebuild_writes_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(schemas, "SCHEMA_DIR", tmp_path)
    call_command("rebuild_content_schemas")
    first = (tmp_path / "create_from_chat.schema.json").read_text()
    assert (tmp_path / "export.schema.json").exists()
    call_command("rebuild_content_schemas")
    assert (tmp_path / "create_from_chat.schema.json").read_text() == first


def test_rebuild_check_fails_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(schemas, "SCHEMA_DIR", tmp_path)  # empty: nothing written
    with pytest.raises(CommandError):
        call_command("rebuild_content_schemas", "--check")


@pytest.mark.parametrize("name", ["event-anchored-campaign", "blog-and-social-series"])
def test_examples_validate_against_schema(name):
    validator = Draft202012Validator(schemas.build_create_from_chat_schema())
    data = json.loads((schemas.SCHEMA_DIR / "examples" / f"{name}.json").read_text())
    assert list(validator.iter_errors(data)) == []
