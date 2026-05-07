import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from surveys.models import (
    Question,
    Response,
    ResponseTheme,
    Survey,
    Theme,
)


@pytest.fixture
def owner(db, surveys_user_perm):
    user = get_user_model().objects.create_user(username="owner", password="pw")
    user.user_permissions.add(surveys_user_perm)
    return user


@pytest.fixture
def other_user(db, surveys_user_perm):
    user = get_user_model().objects.create_user(username="other", password="pw")
    user.user_permissions.add(surveys_user_perm)
    return user


@pytest.fixture
def survey(owner):
    return Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )


@pytest.fixture
def question(survey):
    return Question.objects.create(
        survey=survey, text="?", type=Question.Type.OPEN_TEXT, config={}, order=1
    )


def _resp(question, value):
    return Response.objects.create(
        question=question, submission_uuid=uuid.uuid4(), value=value
    )


def _tag(response, theme, owner, is_rep=False):
    return ResponseTheme.objects.create(
        response=response, theme=theme, tagged_by=owner, is_representative=is_rep
    )


@pytest.mark.django_db
def test_actions_requires_login(client, survey):
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_actions_owner_only(client, survey, other_user):
    client.force_login(other_user)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_action_items_only_show_themes_with_action_item(
    client, survey, question, owner
):
    """Themes with empty action_item land in drafts, not items."""
    with_ai = Theme.objects.create(
        survey=survey, name="Sched", action_item="Add breaks."
    )
    without_ai = Theme.objects.create(survey=survey, name="Vibes")
    r1 = _resp(question, "x")
    r2 = _resp(question, "y")
    _tag(r1, with_ai, owner)
    _tag(r2, without_ai, owner)
    client.force_login(owner)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    items = response.context["items"]
    drafts = response.context["drafts"]
    assert [t.name for t in items] == ["Sched"]
    assert [t.name for t in drafts] == ["Vibes"]


@pytest.mark.django_db
def test_action_items_ordering(client, survey, question, owner):
    """Open before resolved; within bucket, high before medium before low."""
    Theme.objects.create(
        survey=survey,
        name="A-resolved-high",
        action_item="x",
        priority=Theme.Priority.HIGH,
        status=Theme.Status.RESOLVED,
    )
    Theme.objects.create(
        survey=survey,
        name="B-open-low",
        action_item="x",
        priority=Theme.Priority.LOW,
        status=Theme.Status.OPEN,
    )
    Theme.objects.create(
        survey=survey,
        name="C-open-high",
        action_item="x",
        priority=Theme.Priority.HIGH,
        status=Theme.Status.OPEN,
    )
    Theme.objects.create(
        survey=survey,
        name="D-in-progress-medium",
        action_item="x",
        priority=Theme.Priority.MEDIUM,
        status=Theme.Status.IN_PROGRESS,
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    names = [t.name for t in response.context["items"]]
    assert names == [
        "C-open-high",
        "B-open-low",
        "D-in-progress-medium",
        "A-resolved-high",
    ]


@pytest.mark.django_db
def test_actions_shows_representative_quote(client, survey, question, owner):
    theme = Theme.objects.create(survey=survey, name="T", action_item="x")
    r_rep = _resp(question, "this is the rep")
    r_other = _resp(question, "this isn't")
    _tag(r_rep, theme, owner, is_rep=True)
    _tag(r_other, theme, owner)
    client.force_login(owner)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"this is the rep" in response.content
    assert b"this isn't" not in response.content


@pytest.mark.django_db
def test_resolve_toggle(client, survey, owner):
    theme = Theme.objects.create(
        survey=survey, name="T", action_item="x", status=Theme.Status.OPEN
    )
    client.force_login(owner)
    url = reverse(
        "surveys:theme_resolve",
        kwargs={"slug": survey.slug, "theme_id": theme.id},
    )
    response = client.post(url)
    assert response.status_code == 302
    theme.refresh_from_db()
    assert theme.status == Theme.Status.RESOLVED
    response = client.post(url)
    theme.refresh_from_db()
    assert theme.status == Theme.Status.OPEN


@pytest.mark.django_db
def test_resolve_redirects_to_next_url(client, survey, owner):
    theme = Theme.objects.create(survey=survey, name="T", action_item="x")
    client.force_login(owner)
    detail_url = reverse(
        "surveys:theme_detail",
        kwargs={"slug": survey.slug, "theme_id": theme.id},
    )
    response = client.post(
        reverse(
            "surveys:theme_resolve",
            kwargs={"slug": survey.slug, "theme_id": theme.id},
        ),
        {"next": detail_url},
    )
    assert response.status_code == 302
    assert response.url == detail_url


@pytest.mark.django_db
def test_actions_empty_state(client, survey, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"No action items yet" in response.content


@pytest.mark.django_db
def test_actions_drafts_sorted_by_mention_count(client, survey, question, owner):
    a = Theme.objects.create(survey=survey, name="A")
    b = Theme.objects.create(survey=survey, name="B")
    _tag(_resp(question, "1"), a, owner)
    for _ in range(3):
        _tag(_resp(question, "x"), b, owner)
    client.force_login(owner)
    response = client.get(reverse("surveys:actions", kwargs={"slug": survey.slug}))
    drafts = response.context["drafts"]
    assert [t.name for t in drafts] == ["B", "A"]


@pytest.mark.django_db
def test_actions_nav_link_from_dashboard(client, survey, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    actions_url = reverse("surveys:actions", kwargs={"slug": survey.slug})
    assert actions_url.encode() in response.content
