"""Hashtag parsing/merging and the post copy-text behavior."""

import pytest
from django.contrib.auth import get_user_model

from content_planner.hashtags import merge_hashtags, parse_hashtags
from content_planner.models import Campaign, ContentBoard, Post

User = get_user_model()


@pytest.fixture
def board(db):
    owner = User.objects.create_user(username="hbowner")
    return ContentBoard.objects.create(name="B", slug="hb", owner=owner)


# ----------------------------------------------------------- parsing


def test_parse_hashtags_separators_and_hash():
    assert parse_hashtags("PyCon, #python  django") == ["#PyCon", "#python", "#django"]


def test_parse_hashtags_dedup_case_insensitive():
    assert parse_hashtags("#a #A a") == ["#a"]


def test_parse_hashtags_empty():
    assert parse_hashtags("") == []
    assert parse_hashtags(None) == []


def test_merge_hashtags_dedup_across_sources():
    assert merge_hashtags("#a #b", "#b #c") == ["#a", "#b", "#c"]


# ----------------------------------------------------------- model properties


def test_hashtag_list_merges_campaign_and_post(board):
    campaign = Campaign.objects.create(board=board, name="C", hashtags="#PyLadiesCon")
    post = Post.objects.create(
        campaign=campaign, title="P", channel="mastodon", hashtags="python #PyLadiesCon"
    )
    assert post.hashtag_list == ["#PyLadiesCon", "#python"]


def test_copy_text_appends_hashtags_on_social(board):
    campaign = Campaign.objects.create(board=board, name="C", hashtags="#PyLadiesCon")
    post = Post.objects.create(
        campaign=campaign,
        title="P",
        channel="mastodon",
        body_snippet="Hello world",
        hashtags="#python",
    )
    assert post.copy_text == "Hello world\n\n#PyLadiesCon #python"


def test_copy_text_tags_only_when_no_body(board):
    campaign = Campaign.objects.create(board=board, name="C", hashtags="#a")
    post = Post.objects.create(campaign=campaign, title="P", channel="x")
    assert post.copy_text == "#a"


def test_copy_text_plain_body_without_hashtags(board):
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(
        campaign=campaign, title="P", channel="mastodon", body_snippet="Just body"
    )
    assert post.copy_text == "Just body"


def test_copy_text_non_social_channel_ignores_hashtags(board):
    campaign = Campaign.objects.create(board=board, name="C", hashtags="#a")
    post = Post.objects.create(
        campaign=campaign, title="P", channel="blog", body_snippet="Blog body"
    )
    assert post.copy_text == "Blog body"
