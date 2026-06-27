"""Permission helpers and billing seams for content_planner."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from content_planner import billing
from content_planner.models import Campaign, ContentBoard, ContentCollaborator, Post
from content_planner.permissions import (
    can_access_board,
    can_delete_board,
    can_edit_campaign,
    can_edit_post,
    can_manage_collaborators,
    can_publish_post,
    is_content_user,
)
from core.permissions import grant_app_access

User = get_user_model()


@pytest.fixture
def board(db):
    owner = User.objects.create_user(username="owner")
    return ContentBoard.objects.create(name="Board", slug="board", owner=owner)


def test_is_content_user_requires_permission(board):
    user = User.objects.create_user(username="plain")
    assert is_content_user(user) is False
    grant_app_access(user, "content_planner")
    user = User.objects.get(pk=user.pk)  # refresh cached perms
    assert is_content_user(user) is True


def test_is_content_user_anonymous():
    assert is_content_user(AnonymousUser()) is False


def test_can_access_board_anonymous(board):
    assert can_access_board(AnonymousUser(), board) is False


def test_can_access_board_owner(board):
    assert can_access_board(board.owner, board) is True


def test_can_access_board_superuser(board):
    su = User.objects.create_user(username="su")
    su.is_superuser = True
    su.save()
    assert can_access_board(su, board) is True


def test_can_access_board_collaborator(board):
    member = User.objects.create_user(username="member")
    ContentCollaborator.objects.create(board=board, user=member)
    assert can_access_board(member, board) is True


def test_can_access_board_stranger(board):
    stranger = User.objects.create_user(username="stranger")
    assert can_access_board(stranger, board) is False


def test_flat_edit_helpers_follow_board_access(board):
    member = User.objects.create_user(username="member")
    ContentCollaborator.objects.create(board=board, user=member)
    campaign = Campaign.objects.create(board=board, name="C")
    post = Post.objects.create(campaign=campaign, title="P", channel="blog")
    assert can_edit_campaign(member, board) is True
    assert can_edit_post(member, post) is True
    assert can_publish_post(member, post) is True


def test_manage_collaborators_owner_only(board):
    member = User.objects.create_user(username="member")
    ContentCollaborator.objects.create(board=board, user=member)
    assert can_manage_collaborators(board.owner, board) is True
    assert can_manage_collaborators(member, board) is False
    assert can_delete_board(member, board) is False


def test_manage_collaborators_anonymous(board):
    assert can_manage_collaborators(AnonymousUser(), board) is False


def test_manage_collaborators_superuser(board):
    su = User.objects.create_user(username="su")
    su.is_superuser = True
    su.save()
    assert can_manage_collaborators(su, board) is True


def test_billing_seams_are_noops(db):
    user = User.objects.create_user(username="payer")
    assert billing.has_feature(user, "mcp_loop") is True
    assert billing.check_quota(user, "assets", 999) is None
