"""Tests for the abstract bases in ``core.models``.

Use the live concrete subclasses (``SurveyInvitation`` and
``ExpenseInvitation``) rather than test-only subclasses — that keeps
the tests honest about how the abstract is actually used in production
and avoids forcing a schema migration just for a test fixture.
"""

import datetime

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    INVITATION_KEY_LENGTH,
    AbstractInvitation,
    AbstractMembership,
    BaseModel,
    mint_invitation_key,
)
from expenses.models import Event, ExpenseInvitation
from surveys.models import Survey, SurveyInvitation

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        username="owner", password="pw", email="owner@example.com"
    )


@pytest.fixture
def survey(owner):
    return Survey.objects.create(
        owner=owner,
        title="S",
        slug="s",
        status=Survey.Status.PUBLISHED,
    )


@pytest.fixture
def event(owner):
    return Event.objects.create(owner=owner, name="Trip", base_currency="USD")


def test_mint_invitation_key_is_lowercased_and_correct_length():
    key = mint_invitation_key()
    assert len(key) == INVITATION_KEY_LENGTH
    assert key == key.lower()


def test_mint_invitation_key_returns_different_value_each_call():
    # Statistical, not exhaustive — collisions in a 64-char URL-safe key
    # space are vanishingly unlikely.
    keys = {mint_invitation_key() for _ in range(50)}
    assert len(keys) == 50


def test_basemodel_is_abstract():
    assert BaseModel._meta.abstract is True


def test_abstract_invitation_is_abstract():
    assert AbstractInvitation._meta.abstract is True


def test_abstract_membership_is_abstract():
    assert AbstractMembership._meta.abstract is True


@pytest.mark.django_db
def test_concrete_invitations_can_both_mint_keys(survey, event, owner):
    # Two subclasses each get a fresh key; uniqueness is per-table, not
    # cross-table, so the same key value could technically exist in both
    # (probability ~0, but the abstract doesn't try to enforce it).
    si = SurveyInvitation.create(survey=survey, email="x@example.com", inviter=owner)
    ei = ExpenseInvitation.create(event=event, email="y@example.com", inviter=owner)
    assert len(si.key) == INVITATION_KEY_LENGTH
    assert len(ei.key) == INVITATION_KEY_LENGTH


@pytest.mark.django_db
def test_is_accepted_property_reads_accepted_at(survey, owner):
    invitation = SurveyInvitation.create(
        survey=survey, email="x@example.com", inviter=owner
    )
    assert invitation.is_accepted is False
    invitation.accepted_at = timezone.now()
    assert invitation.is_accepted is True


@pytest.mark.django_db
def test_is_expired_reads_subclass_expiry_setting(survey, event, owner):
    # Each subclass declares its own EXPIRY_SETTING attribute, and the
    # abstract's is_expired() reads whatever that names from settings.
    assert SurveyInvitation.EXPIRY_SETTING == "SURVEYS_INVITATION_EXPIRY_DAYS"
    assert ExpenseInvitation.EXPIRY_SETTING == "EXPENSES_INVITATION_EXPIRY_DAYS"
    si = SurveyInvitation.create(survey=survey, email="x@example.com", inviter=owner)
    si.sent_at = timezone.now() - datetime.timedelta(
        days=settings.SURVEYS_INVITATION_EXPIRY_DAYS + 1
    )
    assert si.is_expired() is True
    si.sent_at = timezone.now()
    assert si.is_expired() is False


@pytest.mark.django_db
def test_is_expired_falls_back_to_creation_date_when_unsent(survey, owner):
    # A freshly minted invitation that hasn't been emailed yet still has
    # a sensible expiry clock anchored to creation_date.
    invitation = SurveyInvitation.create(
        survey=survey, email="x@example.com", inviter=owner
    )
    invitation.sent_at = None
    assert invitation.sent_at is None
    assert invitation.is_expired() is False


@pytest.mark.django_db
def test_basemodel_save_bumps_modified_date_on_update_fields(survey):
    # Regression: passing update_fields=["title"] must still bump
    # modified_date — the save() override appends it explicitly.
    original = survey.modified_date
    survey.title = "New title"
    survey.save(update_fields=["title"])
    survey.refresh_from_db()
    assert survey.modified_date > original


@pytest.mark.django_db
def test_concrete_invitation_inherits_reverse_accessor_naming(owner, survey):
    # The %(app_label)s_invitations_sent pattern yields
    # surveys_invitations_sent on User. Verifies the abstract's
    # related_name placeholder is being honored.
    SurveyInvitation.create(survey=survey, email="x@example.com", inviter=owner)
    assert owner.surveys_invitations_sent.count() == 1


@pytest.mark.django_db
def test_concrete_membership_inherits_reverse_accessor_naming(owner, survey):
    # AbstractMembership.user → surveys_memberships on User.
    from surveys.models import SurveyCollaborator

    collab_user = User.objects.create_user(username="c", password="pw")
    SurveyCollaborator.objects.create(survey=survey, user=collab_user)
    assert collab_user.surveys_memberships.count() == 1
