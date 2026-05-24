"""Tests for ``core.permissions`` — Django-canonical app gating.

``has_app_access`` delegates to ``user.has_perm`` so it works through
any of Django's permission sources: direct user perms, group-inherited
perms, superuser auto-True, anonymous auto-False. Group is just one
assignment mechanism; the test fixtures exercise both.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission

from core.permissions import (
    grant_app_access,
    has_app_access,
    revoke_app_access,
)

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="u", password="pw")


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="s", password="pw", email="s@x.com")


@pytest.fixture
def access_surveys_perm(db):
    # Declared on surveys.Survey.Meta.permissions; comes in via migrate.
    return Permission.objects.get(
        codename="access_surveys", content_type__app_label="surveys"
    )


def test_anonymous_user_never_has_access():
    # AnonymousUser.has_perm always returns False — no DB hit, no group lookup.
    assert has_app_access(AnonymousUser(), "surveys") is False


@pytest.mark.django_db
def test_superuser_always_has_access(superuser):
    # Even with no group memberships and no explicit perms, superuser passes.
    assert superuser.groups.count() == 0
    assert superuser.user_permissions.count() == 0
    assert has_app_access(superuser, "surveys") is True
    assert has_app_access(superuser, "expenses") is True


@pytest.mark.django_db
def test_user_without_perm_has_no_access(user):
    assert has_app_access(user, "surveys") is False


@pytest.mark.django_db
def test_direct_user_perm_grants_access(user, access_surveys_perm):
    # Permission attached directly to the user — no group involved.
    # has_perm should see it; has_app_access must agree.
    user.user_permissions.add(access_surveys_perm)
    # Re-fetch to bust Django's per-instance permission cache.
    user = User.objects.get(pk=user.pk)
    assert has_app_access(user, "surveys") is True


@pytest.mark.django_db
def test_grant_then_has_access(user):
    grant_app_access(user, "surveys")
    user = User.objects.get(pk=user.pk)
    assert has_app_access(user, "surveys") is True
    # Other apps stay locked.
    assert has_app_access(user, "expenses") is False


@pytest.mark.django_db
def test_grant_creates_group_with_permission_attached(user, access_surveys_perm):
    # No group exists yet — grant must create it AND attach the access perm.
    assert not Group.objects.filter(name="surveys_users").exists()
    grant_app_access(user, "surveys")
    group = Group.objects.get(name="surveys_users")
    assert access_surveys_perm in group.permissions.all()


@pytest.mark.django_db
def test_grant_is_idempotent(user):
    grant_app_access(user, "surveys")
    grant_app_access(user, "surveys")
    assert Group.objects.filter(name="surveys_users").count() == 1
    assert user.groups.filter(name="surveys_users").count() == 1


@pytest.mark.django_db
def test_grant_raises_if_app_did_not_declare_permission(user):
    # qrcode_manager doesn't have an "access_qrcode_manager" permission.
    # Better to fail loudly than silently create an empty group.
    with pytest.raises(Permission.DoesNotExist):
        grant_app_access(user, "qrcode_manager")


@pytest.mark.django_db
def test_revoke_removes_access(user):
    grant_app_access(user, "surveys")
    user = User.objects.get(pk=user.pk)
    assert has_app_access(user, "surveys") is True
    revoke_app_access(user, "surveys")
    user = User.objects.get(pk=user.pk)
    assert has_app_access(user, "surveys") is False


@pytest.mark.django_db
def test_revoke_on_nonexistent_group_is_a_noop(user):
    # Revoke before any grant — should not raise.
    revoke_app_access(user, "surveys")
    assert has_app_access(user, "surveys") is False


@pytest.mark.django_db
def test_revoke_when_user_not_in_group_is_a_noop(user):
    # Group exists (from another user's grant) but this user is not in it.
    other_user = User.objects.create_user(username="o", password="pw")
    grant_app_access(other_user, "surveys")
    revoke_app_access(user, "surveys")
    assert has_app_access(user, "surveys") is False
