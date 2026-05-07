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
from surveys.services.themes import co_occurring, merge


@pytest.fixture
def owner(db, surveys_user_perm, surveys_create_perm):
    user = get_user_model().objects.create_user(username="owner", password="pw")
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


@pytest.fixture
def other_user(db, surveys_user_perm, surveys_create_perm):
    user = get_user_model().objects.create_user(username="other", password="pw")
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


@pytest.fixture
def survey(owner):
    return Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )


@pytest.fixture
def question(survey):
    return Question.objects.create(
        survey=survey,
        text="Anything else?",
        type=Question.Type.OPEN_TEXT,
        config={},
        order=1,
    )


def _response(question, value):
    return Response.objects.create(
        question=question, submission_uuid=uuid.uuid4(), value=value
    )


def _tag(response, theme, user, is_rep=False):
    return ResponseTheme.objects.create(
        response=response, theme=theme, tagged_by=user, is_representative=is_rep
    )


@pytest.mark.django_db
def test_theme_detail_requires_login(client, survey):
    theme = Theme.objects.create(survey=survey, name="T")
    url = reverse(
        "surveys:theme_detail", kwargs={"slug": survey.slug, "theme_id": theme.id}
    )
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_theme_detail_owner_only(client, survey, other_user):
    theme = Theme.objects.create(survey=survey, name="T")
    client.force_login(other_user)
    url = reverse(
        "surveys:theme_detail", kwargs={"slug": survey.slug, "theme_id": theme.id}
    )
    response = client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_theme_detail_renders_with_responses(client, survey, question, owner):
    theme = Theme.objects.create(survey=survey, name="Scheduling")
    r = _response(question, "Tracks overlap.")
    _tag(r, theme, owner)
    client.force_login(owner)
    url = reverse(
        "surveys:theme_detail", kwargs={"slug": survey.slug, "theme_id": theme.id}
    )
    response = client.get(url)
    assert response.status_code == 200
    assert b"Scheduling" in response.content
    assert b"Tracks overlap." in response.content
    assert b"Action item" in response.content


@pytest.mark.django_db
def test_save_action_item(client, survey, owner):
    theme = Theme.objects.create(survey=survey, name="Scheduling")
    client.force_login(owner)
    url = reverse(
        "surveys:theme_detail", kwargs={"slug": survey.slug, "theme_id": theme.id}
    )
    response = client.post(
        url,
        {
            "name": "Scheduling",
            "tag": "ops",
            "action_item": "Add 30-minute breaks between tracks.",
            "priority": "high",
            "status": "in_progress",
        },
    )
    assert response.status_code == 302
    theme.refresh_from_db()
    assert theme.action_item.startswith("Add 30-minute")
    assert theme.priority == Theme.Priority.HIGH
    assert theme.status == Theme.Status.IN_PROGRESS
    assert theme.tag == "ops"


@pytest.mark.django_db
def test_star_marks_representative(client, survey, question, owner):
    theme = Theme.objects.create(survey=survey, name="T")
    r1 = _response(question, "one")
    r2 = _response(question, "two")
    rt1 = _tag(r1, theme, owner)
    _tag(r2, theme, owner)
    client.force_login(owner)
    url = reverse(
        "surveys:theme_star",
        kwargs={"slug": survey.slug, "theme_id": theme.id, "response_id": r1.id},
    )
    response = client.post(url)
    assert response.status_code == 302
    rt1.refresh_from_db()
    assert rt1.is_representative is True


@pytest.mark.django_db
def test_star_only_one_per_theme(client, survey, question, owner):
    """Starring a different response unstars the previous one — DB constraint."""
    theme = Theme.objects.create(survey=survey, name="T")
    r1 = _response(question, "one")
    r2 = _response(question, "two")
    rt1 = _tag(r1, theme, owner, is_rep=True)
    rt2 = _tag(r2, theme, owner)
    client.force_login(owner)
    response = client.post(
        reverse(
            "surveys:theme_star",
            kwargs={"slug": survey.slug, "theme_id": theme.id, "response_id": r2.id},
        )
    )
    assert response.status_code == 302
    rt1.refresh_from_db()
    rt2.refresh_from_db()
    assert rt1.is_representative is False
    assert rt2.is_representative is True


@pytest.mark.django_db
def test_star_toggle_off(client, survey, question, owner):
    theme = Theme.objects.create(survey=survey, name="T")
    r = _response(question, "x")
    rt = _tag(r, theme, owner, is_rep=True)
    client.force_login(owner)
    client.post(
        reverse(
            "surveys:theme_star",
            kwargs={"slug": survey.slug, "theme_id": theme.id, "response_id": r.id},
        )
    )
    rt.refresh_from_db()
    assert rt.is_representative is False


@pytest.mark.django_db
def test_untag_removes_response_theme_row(client, survey, question, owner):
    theme = Theme.objects.create(survey=survey, name="T")
    r = _response(question, "x")
    _tag(r, theme, owner)
    client.force_login(owner)
    response = client.post(
        reverse(
            "surveys:theme_untag",
            kwargs={"slug": survey.slug, "theme_id": theme.id, "response_id": r.id},
        )
    )
    assert response.status_code == 302
    assert ResponseTheme.objects.filter(theme=theme, response=r).count() == 0


@pytest.mark.django_db
def test_co_occurring_counts_shared_responses(survey, question, owner):
    a = Theme.objects.create(survey=survey, name="A")
    b = Theme.objects.create(survey=survey, name="B")
    c = Theme.objects.create(survey=survey, name="C")
    r1 = _response(question, "1")
    r2 = _response(question, "2")
    r3 = _response(question, "3")
    _tag(r1, a, owner)
    _tag(r1, b, owner)
    _tag(r2, a, owner)
    _tag(r2, b, owner)
    _tag(r3, a, owner)
    _tag(r3, c, owner)
    pairs = co_occurring(a)
    by_name = {t.name: n for t, n in pairs}
    assert by_name == {"B": 2, "C": 1}


@pytest.mark.django_db
def test_co_occurring_excludes_other_surveys(owner, other_user):
    s1 = Survey.objects.create(owner=owner, title="A", slug="a")
    s2 = Survey.objects.create(owner=owner, title="B", slug="b")
    q1 = Question.objects.create(
        survey=s1, text="Q", type=Question.Type.OPEN_TEXT, order=1
    )
    q2 = Question.objects.create(
        survey=s2, text="Q", type=Question.Type.OPEN_TEXT, order=1
    )
    t1 = Theme.objects.create(survey=s1, name="X")
    t2 = Theme.objects.create(survey=s2, name="X")
    r = _response(q1, "x")
    r2 = _response(q2, "y")
    _tag(r, t1, owner)
    _tag(r2, t2, owner)
    assert co_occurring(t1) == []


@pytest.mark.django_db
def test_merge_moves_responses_and_deletes_source(survey, question, owner):
    src = Theme.objects.create(survey=survey, name="Src")
    tgt = Theme.objects.create(survey=survey, name="Tgt")
    r1 = _response(question, "1")
    r2 = _response(question, "2")
    _tag(r1, src, owner, is_rep=True)
    _tag(r2, src, owner)
    merge(src, tgt)
    assert not Theme.objects.filter(id=src.id).exists()
    assert set(tgt.responses.values_list("id", flat=True)) == {r1.id, r2.id}
    assert ResponseTheme.objects.filter(theme=tgt, is_representative=True).count() == 0


@pytest.mark.django_db
def test_merge_collapses_duplicate_response(survey, question, owner):
    """A response already on target shouldn't get a second ResponseTheme row."""
    src = Theme.objects.create(survey=survey, name="Src")
    tgt = Theme.objects.create(survey=survey, name="Tgt")
    r = _response(question, "shared")
    _tag(r, src, owner)
    _tag(r, tgt, owner)
    merge(src, tgt)
    assert ResponseTheme.objects.filter(theme=tgt, response=r).count() == 1


@pytest.mark.django_db
def test_merge_preserves_target_representative(survey, question, owner):
    """Target's existing rep stays after merge; source's rep is dropped."""
    src = Theme.objects.create(survey=survey, name="Src")
    tgt = Theme.objects.create(survey=survey, name="Tgt")
    r_target = _response(question, "tgt")
    r_source = _response(question, "src")
    _tag(r_target, tgt, owner, is_rep=True)
    _tag(r_source, src, owner, is_rep=True)
    merge(src, tgt)
    rep_rows = ResponseTheme.objects.filter(theme=tgt, is_representative=True)
    assert rep_rows.count() == 1
    assert rep_rows.first().response_id == r_target.id


@pytest.mark.django_db
def test_merge_view_redirects_to_target(client, survey, question, owner):
    src = Theme.objects.create(survey=survey, name="Src")
    tgt = Theme.objects.create(survey=survey, name="Tgt")
    r = _response(question, "x")
    _tag(r, src, owner)
    client.force_login(owner)
    url = reverse(
        "surveys:theme_merge",
        kwargs={"slug": survey.slug, "theme_id": src.id},
    )
    response = client.post(url, {"target_theme_id": tgt.id})
    assert response.status_code == 302
    assert response.url == reverse(
        "surveys:theme_detail",
        kwargs={"slug": survey.slug, "theme_id": tgt.id},
    )
    assert not Theme.objects.filter(id=src.id).exists()


@pytest.mark.django_db
def test_merge_rejects_cross_survey(owner):
    s1 = Survey.objects.create(owner=owner, title="A", slug="a")
    s2 = Survey.objects.create(owner=owner, title="B", slug="b")
    src = Theme.objects.create(survey=s1, name="X")
    tgt = Theme.objects.create(survey=s2, name="X")
    with pytest.raises(ValueError):
        merge(src, tgt)
