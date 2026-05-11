import pytest
from django.contrib.auth import get_user_model

from surveys.models import Survey, SurveyCollaborator
from surveys.services.recipients import (
    display_name,
    join_with_and,
    recipient_names,
)


@pytest.mark.django_db
def test_display_name_uses_full_name_when_present():
    user = get_user_model().objects.create_user(
        username="achen", password="pw", first_name="Alice", last_name="Chen"
    )
    assert display_name(user) == "Alice Chen"


@pytest.mark.django_db
def test_display_name_falls_back_to_username_when_no_full_name():
    user = get_user_model().objects.create_user(username="lonename", password="pw")
    assert display_name(user) == "lonename"


@pytest.mark.django_db
def test_display_name_strips_a_first_or_last_only_user_to_username():
    """get_full_name() returns 'Alice ' (with trailing space) when only
    first_name is set. The strip() in display_name() keeps the rendered
    name from carrying that trailing space — but we still prefer the
    real name over the username when at least one name field is set."""
    only_first = get_user_model().objects.create_user(
        username="alicedoe", password="pw", first_name="Alice"
    )
    assert display_name(only_first) == "Alice"


@pytest.mark.django_db
def test_recipient_names_owner_only(db):
    owner = get_user_model().objects.create_user(
        username="alice", password="pw", first_name="Alice", last_name="Chen"
    )
    survey = Survey.objects.create(owner=owner, title="S", slug="s")
    assert recipient_names(survey) == ["Alice Chen"]


@pytest.mark.django_db
def test_recipient_names_owner_first_then_collaborators_by_join_order():
    owner = get_user_model().objects.create_user(
        username="o", password="pw", first_name="Alice", last_name="Chen"
    )
    survey = Survey.objects.create(owner=owner, title="S", slug="s")
    first_collab = get_user_model().objects.create_user(
        username="b", password="pw", first_name="Bob", last_name="Builder"
    )
    second_collab = get_user_model().objects.create_user(
        username="c", password="pw", first_name="Carol", last_name="Carter"
    )
    SurveyCollaborator.objects.create(survey=survey, user=first_collab)
    SurveyCollaborator.objects.create(survey=survey, user=second_collab)
    assert recipient_names(survey) == ["Alice Chen", "Bob Builder", "Carol Carter"]


@pytest.mark.django_db
def test_recipient_names_falls_back_to_username_for_unnamed_users():
    owner = get_user_model().objects.create_user(username="onlyowner", password="pw")
    survey = Survey.objects.create(owner=owner, title="S", slug="s")
    collab = get_user_model().objects.create_user(username="onlycollab", password="pw")
    SurveyCollaborator.objects.create(survey=survey, user=collab)
    assert recipient_names(survey) == ["onlyowner", "onlycollab"]


def test_join_with_and_empty():
    assert join_with_and([]) == ""


def test_join_with_and_single():
    assert join_with_and(["Alice"]) == "Alice"


def test_join_with_and_two():
    assert join_with_and(["Alice", "Bob"]) == "Alice and Bob"


def test_join_with_and_three_uses_oxford_comma():
    assert join_with_and(["Alice", "Bob", "Carol"]) == "Alice, Bob, and Carol"


def test_join_with_and_four_uses_oxford_comma():
    assert (
        join_with_and(["Alice", "Bob", "Carol", "Dan"]) == "Alice, Bob, Carol, and Dan"
    )
