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
from surveys.services.triage import (
    apply_triage,
    next_to_review,
    progress,
    untriaged_queue,
)


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
def survey_with_open_text(owner):
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    q = Question.objects.create(
        survey=survey,
        text="Anything else?",
        type=Question.Type.OPEN_TEXT,
        config={},
        order=1,
    )
    return survey, q


def _new_response(question, text):
    return Response.objects.create(
        question=question, submission_uuid=uuid.uuid4(), value=text
    )


@pytest.mark.django_db
def test_untriaged_queue_excludes_already_tagged(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "first")
    r2 = _new_response(q, "second")
    theme = Theme.objects.create(survey=survey, name="X")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    queue = list(untriaged_queue(survey))
    assert queue == [r2]


@pytest.mark.django_db
def test_next_to_review_skip_via_after(survey_with_open_text):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "first")
    r2 = _new_response(q, "second")
    assert next_to_review(survey).id == r1.id
    assert next_to_review(survey, after_id=r1.id).id == r2.id
    assert next_to_review(survey, after_id=r2.id) is None


@pytest.mark.django_db
def test_progress_counts(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "a")
    _new_response(q, "b")
    _new_response(q, "c")
    theme = Theme.objects.create(survey=survey, name="T")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    assert progress(survey) == (1, 3)


@pytest.mark.django_db
def test_apply_triage_existing_themes(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    t1 = Theme.objects.create(survey=survey, name="Scheduling")
    t2 = Theme.objects.create(survey=survey, name="Venue")
    apply_triage(
        response=r,
        theme_ids=[t1.id, t2.id],
        new_theme_name=None,
        quick_action=None,
        user=owner,
    )
    assert set(r.themes.values_list("name", flat=True)) == {"Scheduling", "Venue"}


@pytest.mark.django_db
def test_apply_triage_new_theme_inline(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    apply_triage(
        response=r,
        theme_ids=[],
        new_theme_name="Programming",
        quick_action=None,
        user=owner,
    )
    assert Theme.objects.filter(survey=survey, name="Programming").exists()
    assert r.themes.first().name == "Programming"


@pytest.mark.django_db
def test_apply_triage_quick_action_creates_theme(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "thank you so much")
    apply_triage(
        response=r,
        theme_ids=[],
        new_theme_name=None,
        quick_action="appreciation",
        user=owner,
    )
    assert r.themes.first().name == "Appreciation"


@pytest.mark.django_db
def test_apply_triage_quick_action_reuses_existing_theme(survey_with_open_text, owner):
    survey, q = survey_with_open_text
    Theme.objects.create(survey=survey, name="Not actionable")
    r = _new_response(q, "noise")
    apply_triage(
        response=r,
        theme_ids=[],
        new_theme_name=None,
        quick_action="not_actionable",
        user=owner,
    )
    assert Theme.objects.filter(survey=survey, name="Not actionable").count() == 1


@pytest.mark.django_db
def test_triage_view_requires_login(client, survey_with_open_text):
    survey, _ = survey_with_open_text
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_triage_view_requires_ownership(client, survey_with_open_text, other_user):
    survey, _ = survey_with_open_text
    client.force_login(other_user)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_triage_view_renders_next_response(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    _new_response(q, "Loved it.")
    client.force_login(owner)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"Loved it." in response.content
    assert b"Appreciation" in response.content
    assert b"Not actionable" in response.content
    assert b"Skip" in response.content


@pytest.mark.django_db
def test_triage_view_done_when_queue_empty(client, survey_with_open_text, owner):
    survey, _ = survey_with_open_text
    client.force_login(owner)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"All caught up" in response.content


@pytest.mark.django_db
def test_triage_post_applies_tags_and_redirects(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    theme = Theme.objects.create(survey=survey, name="Scheduling")
    client.force_login(owner)
    response = client.post(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {
            "response_id": r.id,
            "theme_ids": [theme.id],
            "action": "next",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("surveys:triage", kwargs={"slug": survey.slug})
    assert r.themes.first().name == "Scheduling"


@pytest.mark.django_db
def test_triage_post_skip_advances_with_after(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "one")
    _new_response(q, "two")
    client.force_login(owner)
    response = client.post(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"response_id": r1.id, "action": "skip"},
    )
    assert response.status_code == 302
    assert f"after={r1.id}" in response.url
    assert r1.themes.count() == 0


@pytest.mark.django_db
def test_appreciation_clears_other_themes(survey_with_open_text, owner):
    """Quick action is mutually exclusive with regular themes."""
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    scheduling = Theme.objects.create(survey=survey, name="Scheduling")
    ResponseTheme.objects.create(response=r, theme=scheduling, tagged_by=owner)
    apply_triage(
        response=r,
        theme_ids=[],
        new_theme_name=None,
        quick_action="appreciation",
        user=owner,
    )
    names = list(r.themes.values_list("name", flat=True))
    assert names == ["Appreciation"]


@pytest.mark.django_db
def test_regular_theme_clears_quick_action_sentinel(survey_with_open_text, owner):
    """Adding a real theme to an appreciated response drops the sentinel."""
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    appreciation = Theme.objects.create(survey=survey, name="Appreciation")
    ResponseTheme.objects.create(response=r, theme=appreciation, tagged_by=owner)
    sched = Theme.objects.create(survey=survey, name="Scheduling")
    apply_triage(
        response=r,
        theme_ids=[sched.id],
        new_theme_name=None,
        quick_action=None,
        user=owner,
    )
    names = sorted(r.themes.values_list("name", flat=True))
    assert names == ["Scheduling"]


@pytest.mark.django_db
def test_new_theme_name_matches_case_insensitively(survey_with_open_text, owner):
    """Don't create 'scheduling' next to existing 'Scheduling'."""
    survey, q = survey_with_open_text
    r = _new_response(q, "x")
    Theme.objects.create(survey=survey, name="Scheduling")
    apply_triage(
        response=r,
        theme_ids=[],
        new_theme_name="scheduling",
        quick_action=None,
        user=owner,
    )
    assert Theme.objects.filter(survey=survey, name__iexact="scheduling").count() == 1
    assert r.themes.first().name == "Scheduling"


@pytest.mark.django_db
def test_whitespace_only_response_auto_marked_not_actionable(
    client, survey_with_open_text, owner
):
    """First-view side effect: auto-tag whitespace responses."""
    survey, q = survey_with_open_text
    r = _new_response(q, "   \n  ")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}) + f"?response={r.id}"
    )
    assert response.status_code == 200
    r.refresh_from_db()
    assert r.themes.count() == 1
    assert r.themes.first().name == "Not actionable"


@pytest.mark.django_db
def test_non_whitespace_response_not_auto_marked(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "actual text")
    client.force_login(owner)
    client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}) + f"?response={r.id}"
    )
    r.refresh_from_db()
    assert r.themes.count() == 0


@pytest.mark.django_db
def test_triage_post_quick_action_creates_and_tags(
    client, survey_with_open_text, owner
):
    survey, q = survey_with_open_text
    r = _new_response(q, "noise")
    client.force_login(owner)
    response = client.post(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"response_id": r.id, "action": "not_actionable"},
    )
    assert response.status_code == 302
    assert r.themes.first().name == "Not actionable"


@pytest.mark.django_db
def test_triage_view_specific_response_via_query(client, survey_with_open_text, owner):
    """`?response=<id>` opens that specific response, even if already triaged."""
    survey, q = survey_with_open_text
    r1 = _new_response(q, "first")
    _new_response(q, "second")
    theme = Theme.objects.create(survey=survey, name="X")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}) + f"?response={r1.id}"
    )
    assert response.status_code == 200
    assert b"first" in response.content
    """Already-tagged themes should be pre-checked so the user can edit."""
    assert response.context["tagged_theme_ids"] == {theme.id}


@pytest.mark.django_db
def test_triage_view_renders_prev_next_links(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "one")
    r2 = _new_response(q, "two")
    r3 = _new_response(q, "three")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}) + f"?response={r2.id}"
    )
    assert response.status_code == 200
    assert response.context["prev_id"] == r1.id
    assert response.context["next_id"] == r3.id


@pytest.mark.django_db
def test_triage_renders_progress_bar(client, survey_with_open_text, owner):
    """Visual progress bar with role/aria + width % matching reviewed/total."""
    survey, q = survey_with_open_text
    r1 = _new_response(q, "first")
    _new_response(q, "second")
    _new_response(q, "third")
    _new_response(q, "fourth")
    theme = Theme.objects.create(survey=survey, name="X")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    client.force_login(owner)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'role="progressbar"' in response.content
    assert b'aria-valuenow="1"' in response.content
    assert b'aria-valuemax="4"' in response.content


@pytest.mark.django_db
def test_triage_renders_meta_pills_and_peek_link(client, survey_with_open_text, owner):
    """Meta pills above the quote and the peek-action-items link."""
    survey, q = survey_with_open_text
    _new_response(q, "feedback")
    client.force_login(owner)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"submitted" in response.content
    assert b"peek action items" in response.content


@pytest.mark.django_db
def test_triage_view_no_prev_at_start(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r1 = _new_response(q, "one")
    _new_response(q, "two")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}) + f"?response={r1.id}"
    )
    assert response.context["prev_id"] is None


@pytest.mark.django_db
def test_triage_post_new_theme_inline(client, survey_with_open_text, owner):
    survey, q = survey_with_open_text
    r = _new_response(q, "feedback")
    client.force_login(owner)
    response = client.post(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {
            "response_id": r.id,
            "new_theme_name": "Programming",
            "action": "next",
        },
    )
    assert response.status_code == 302
    assert Theme.objects.filter(survey=survey, name="Programming").exists()
    assert r.themes.first().name == "Programming"


# Per-question triage scope. Browse-text launches triage filtered to a
# single open-text question via ``?question=<id>``. The scope must survive
# POST → redirect, prev/next nav, skip, and the "all caught up" state.


@pytest.fixture
def survey_with_two_open_text(owner):
    """Two text questions on one survey — needed to verify scoping is
    strict (responses to the OTHER question must not appear)."""
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    q1 = Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, order=1
    )
    q2 = Question.objects.create(
        survey=survey, text="Q2", type=Question.Type.OPEN_TEXT, order=2
    )
    return survey, q1, q2


@pytest.mark.django_db
def test_untriaged_queue_respects_question_scope(survey_with_two_open_text):
    from surveys.services.triage import untriaged_queue

    survey, q1, q2 = survey_with_two_open_text
    r1 = _new_response(q1, "for q1")
    r2 = _new_response(q2, "for q2")
    scoped = list(untriaged_queue(survey, question_id=q1.id))
    assert scoped == [r1]
    scoped2 = list(untriaged_queue(survey, question_id=q2.id))
    assert scoped2 == [r2]


@pytest.mark.django_db
def test_next_to_review_respects_question_scope(survey_with_two_open_text):
    survey, q1, q2 = survey_with_two_open_text
    _new_response(q1, "for q1")
    r_other = _new_response(q2, "for q2")
    # Even though q2's response was created second, the scoped call must
    # skip q1 entirely and pick q2's response.
    nxt = next_to_review(survey, question_id=q2.id)
    assert nxt == r_other


@pytest.mark.django_db
def test_progress_respects_question_scope(survey_with_two_open_text, owner):
    survey, q1, q2 = survey_with_two_open_text
    r1 = _new_response(q1, "a")
    _new_response(q2, "b")
    _new_response(q2, "c")
    theme = Theme.objects.create(survey=survey, name="T")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    assert progress(survey, question_id=q1.id) == (1, 1)
    assert progress(survey, question_id=q2.id) == (0, 2)


@pytest.mark.django_db
def test_queue_neighbors_respects_question_scope(survey_with_two_open_text):
    from surveys.services.triage import queue_neighbors

    survey, q1, q2 = survey_with_two_open_text
    r1a = _new_response(q1, "q1-a")
    r1b = _new_response(q1, "q1-b")
    _new_response(q2, "q2 should not interleave")
    prev_id, next_id = queue_neighbors(survey, r1a.id, question_id=q1.id)
    assert prev_id is None
    assert next_id == r1b.id
    prev_id, next_id = queue_neighbors(survey, r1b.id, question_id=q1.id)
    assert prev_id == r1a.id
    assert next_id is None


@pytest.mark.django_db
def test_triage_view_with_question_scope_picks_only_that_question(
    client, survey_with_two_open_text, owner
):
    survey, q1, q2 = survey_with_two_open_text
    _new_response(q1, "from q1")
    r_q2 = _new_response(q2, "from q2")
    client.force_login(owner)
    url = reverse("surveys:triage", kwargs={"slug": survey.slug})
    response = client.get(url, {"question": q2.id})
    assert response.status_code == 200
    assert b"from q2" in response.content
    assert b"from q1" not in response.content
    # Scope banner surfaces so the user sees they're filtered.
    assert b"Focused on" in response.content
    # Hidden input form posts to the same URL — current URL carries the
    # scope query string, so POSTs preserve it without an extra field.
    assert f'value="{r_q2.id}"'.encode() in response.content


@pytest.mark.django_db
def test_triage_view_404_on_unknown_question_scope(
    client, survey_with_two_open_text, owner
):
    survey, _, _ = survey_with_two_open_text
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"question": 99999},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_triage_view_404_on_non_int_question_scope(
    client, survey_with_two_open_text, owner
):
    survey, _, _ = survey_with_two_open_text
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"question": "abc"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_triage_view_404_on_non_text_question_scope(client, owner):
    """A rating question's id can't scope triage — triage is text-only."""
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    rating = Question.objects.create(
        survey=survey, text="Rate", type=Question.Type.RATING, order=1
    )
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"question": rating.id},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_triage_post_preserves_scope_on_redirect(
    client, survey_with_two_open_text, owner
):
    survey, q1, _ = survey_with_two_open_text
    r = _new_response(q1, "tag me")
    theme = Theme.objects.create(survey=survey, name="T")
    client.force_login(owner)
    url = reverse("surveys:triage", kwargs={"slug": survey.slug})
    response = client.post(
        f"{url}?question={q1.id}",
        {"response_id": r.id, "theme_ids": [theme.id], "action": "next"},
    )
    assert response.status_code == 302
    assert response.url == f"{url}?question={q1.id}"


@pytest.mark.django_db
def test_triage_post_skip_preserves_scope(client, survey_with_two_open_text, owner):
    survey, q1, _ = survey_with_two_open_text
    r1 = _new_response(q1, "one")
    _new_response(q1, "two")
    client.force_login(owner)
    url = reverse("surveys:triage", kwargs={"slug": survey.slug})
    response = client.post(
        f"{url}?question={q1.id}",
        {"response_id": r1.id, "action": "skip"},
    )
    assert response.status_code == 302
    assert f"question={q1.id}" in response.url
    assert f"after={r1.id}" in response.url


@pytest.mark.django_db
def test_triage_done_page_shows_scope_and_unscope_link(
    client, survey_with_two_open_text, owner
):
    """When triage runs out of responses inside a question scope, the
    done page surfaces the focused question and an "Triage all
    questions" escape hatch back to the global queue."""
    survey, q1, _ = survey_with_two_open_text
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"question": q1.id},
    )
    assert response.status_code == 200
    assert b"Q1" in response.content
    assert b"Triage all questions" in response.content


@pytest.mark.django_db
def test_triage_prev_next_links_preserve_scope(
    client, survey_with_two_open_text, owner
):
    survey, q1, _ = survey_with_two_open_text
    r1 = _new_response(q1, "first")
    _new_response(q1, "second")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:triage", kwargs={"slug": survey.slug}),
        {"question": q1.id, "response": r1.id},
    )
    body = response.content.decode()
    # Next link must carry both the response id and the question scope.
    assert f"question={q1.id}" in body
