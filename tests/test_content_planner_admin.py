"""Admin behavior for content_planner — the created_by stamping seam."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model

from content_planner.admin import PostAdmin
from content_planner.models import Campaign, ContentBoard, Post

User = get_user_model()


@pytest.fixture
def post(db):
    owner = User.objects.create_user(username="owner")
    board = ContentBoard.objects.create(name="Board", slug="board", owner=owner)
    campaign = Campaign.objects.create(board=board, name="C")
    return Post(campaign=campaign, title="P", channel="blog")


class _Request:
    def __init__(self, user):
        self.user = user


def test_save_model_stamps_created_by_when_unset(post):
    actor = User.objects.create_user(username="drafter")
    admin = PostAdmin(Post, AdminSite())
    admin.save_model(_Request(actor), post, form=None, change=False)
    post.refresh_from_db()
    assert post.created_by == actor


def test_save_model_preserves_existing_created_by(post):
    original = User.objects.create_user(username="original")
    editor = User.objects.create_user(username="editor")
    post.created_by = original
    post.save()
    admin = PostAdmin(Post, AdminSite())
    admin.save_model(_Request(editor), post, form=None, change=True)
    post.refresh_from_db()
    assert post.created_by == original
