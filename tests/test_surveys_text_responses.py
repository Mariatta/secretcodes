"""Tests for the read-only Browse-text overview page.

Covers the ``surveys:text_responses`` URL/view that lists every open-text
response on a single page, grouped by question. The page is read-only —
all tagging happens in triage, which this page links into with
``?question=<id>`` scope.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from surveys.models import (
    Question,
    Response,
    ResponseTheme,
    Survey,
    SurveyCollaborator,
    Theme,
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
def survey_with_two_text_questions(owner):
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    q1 = Question.objects.create(
        survey=survey,
        text="What went well?",
        type=Question.Type.OPEN_TEXT,
        config={},
        order=1,
    )
    q2 = Question.objects.create(
        survey=survey,
        text="What could improve?",
        type=Question.Type.OPEN_TEXT,
        config={},
        order=2,
    )
    return survey, q1, q2


def _new_response(question, text):
    return Response.objects.create(
        question=question, submission_uuid=uuid.uuid4(), value=text
    )


@pytest.mark.django_db
def test_text_responses_requires_login(client, survey_with_two_text_questions):
    survey, _, _ = survey_with_two_text_questions
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_text_responses_requires_access(
    client, survey_with_two_text_questions, other_user
):
    survey, _, _ = survey_with_two_text_questions
    client.force_login(other_user)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_text_responses_404_for_unknown_slug(client, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:text_responses", kwargs={"slug": "nope"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_text_responses_collaborator_can_access(
    client, survey_with_two_text_questions, surveys_user_perm
):
    survey, _, _ = survey_with_two_text_questions
    collab = get_user_model().objects.create_user(username="c", password="pw")
    collab.user_permissions.add(surveys_user_perm)
    SurveyCollaborator.objects.create(survey=survey, user=collab)
    client.force_login(collab)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_text_responses_groups_by_question(
    client, survey_with_two_text_questions, owner
):
    survey, q1, q2 = survey_with_two_text_questions
    _new_response(q1, "Coffee was great.")
    _new_response(q2, "Room was cold.")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 200
    body = response.content
    assert b"What went well?" in body
    assert b"What could improve?" in body
    assert b"Coffee was great." in body
    assert b"Room was cold." in body
    assert body.index(b"What went well?") < body.index(b"What could improve?")
    assert body.index(b"Coffee was great.") < body.index(b"Room was cold.")


@pytest.mark.django_db
def test_text_responses_shows_existing_tags_as_pills(
    client, survey_with_two_text_questions, owner
):
    """Existing theme tags render as read-only pills under each response."""
    survey, q1, _ = survey_with_two_text_questions
    r = _new_response(q1, "Felt rushed.")
    theme = Theme.objects.create(survey=survey, name="Scheduling")
    ResponseTheme.objects.create(response=r, theme=theme, tagged_by=owner)
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    body = response.content.decode()
    assert "Scheduling" in body
    # No <form>/<input> for tagging — this page is read-only.
    assert "<input" not in body or "csrf" not in body
    assert "theme_ids" not in body
    assert "new_theme_name" not in body


@pytest.mark.django_db
def test_text_responses_anchor_per_response(
    client, survey_with_two_text_questions, owner
):
    survey, q1, _ = survey_with_two_text_questions
    r = _new_response(q1, "Anchor me.")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert f'id="response-{r.id}"'.encode() in response.content


@pytest.mark.django_db
def test_text_responses_ignores_non_text_questions(client, owner):
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Rate it",
        type=Question.Type.RATING,
        config={"max": 5},
        order=1,
    )
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 200
    assert b"No open-text questions" in response.content
    assert b"Rate it" not in response.content


@pytest.mark.django_db
def test_text_responses_empty_question_renders_helper(
    client, survey_with_two_text_questions, owner
):
    survey, _, _ = survey_with_two_text_questions
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 200
    assert b"No responses yet." in response.content


@pytest.mark.django_db
def test_text_responses_section_links_into_scoped_triage(
    client, survey_with_two_text_questions, owner
):
    """The "Triage these →" CTA appears only when there are responses,
    and carries the per-question scope param."""
    survey, q1, q2 = survey_with_two_text_questions
    _new_response(q1, "Anything.")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    body = response.content.decode()
    triage_url = reverse("surveys:triage", kwargs={"slug": survey.slug})
    assert f'{triage_url}?question={q1.id}"' in body
    # q2 has no responses, so its section should not show the CTA URL.
    assert f'{triage_url}?question={q2.id}"' not in body


@pytest.mark.django_db
def test_text_responses_cards_have_no_per_response_triage_link(
    client, survey_with_two_text_questions, owner
):
    """Per-card "Edit in triage" was removed — duplicates the section CTA.
    The card is purely read-only; editing happens via the section header."""
    survey, q1, _ = survey_with_two_text_questions
    r = _new_response(q1, "Read me.")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    body = response.content.decode()
    triage_url = reverse("surveys:triage", kwargs={"slug": survey.slug})
    assert "Edit in triage" not in body
    assert f"{triage_url}?question={q1.id}&response={r.id}" not in body


@pytest.mark.django_db
def test_text_responses_untriaged_badge(client, survey_with_two_text_questions, owner):
    survey, q1, _ = survey_with_two_text_questions
    r1 = _new_response(q1, "First")
    _new_response(q1, "Second")
    theme = Theme.objects.create(survey=survey, name="Tag")
    ResponseTheme.objects.create(response=r1, theme=theme, tagged_by=owner)
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    )
    assert b"1 untriaged" in response.content


@pytest.mark.django_db
def test_text_responses_subnav_link_present(
    client, survey_with_two_text_questions, owner
):
    survey, _, _ = survey_with_two_text_questions
    client.force_login(owner)
    response = client.get(reverse("surveys:triage", kwargs={"slug": survey.slug}))
    assert (
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}).encode()
        in response.content
    )


# Per-question scope on Browse text. The Results page links here with
# ``?question=<id>`` so the organizer lands focused on one question. Scope
# shows a banner + summary line, hides other questions, and 404s on bad ids.


@pytest.mark.django_db
def test_text_responses_question_scope_filters_to_one_question(
    client, survey_with_two_text_questions, owner
):
    survey, q1, q2 = survey_with_two_text_questions
    _new_response(q1, "answer to q1")
    _new_response(q2, "answer to q2")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}),
        {"question": q1.id},
    )
    assert response.status_code == 200
    body = response.content
    assert b"answer to q1" in body
    assert b"answer to q2" not in body
    assert b"What went well?" in body
    assert b"What could improve?" not in body


@pytest.mark.django_db
def test_text_responses_question_scope_renders_banner(
    client, survey_with_two_text_questions, owner
):
    survey, q1, _ = survey_with_two_text_questions
    _new_response(q1, "x")
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}),
        {"question": q1.id},
    )
    body = response.content
    assert b"Showing only" in body
    assert b"Show all text questions" in body


@pytest.mark.django_db
def test_text_responses_question_scope_404_on_unknown(
    client, survey_with_two_text_questions, owner
):
    survey, _, _ = survey_with_two_text_questions
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}),
        {"question": 99999},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_text_responses_question_scope_404_on_non_text(client, owner):
    """A rating question's id can't scope Browse text — it's text-only."""
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    rating = Question.objects.create(
        survey=survey, text="Rate", type=Question.Type.RATING, order=1
    )
    Question.objects.create(
        survey=survey, text="Notes", type=Question.Type.OPEN_TEXT, order=2
    )
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}),
        {"question": rating.id},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_text_responses_question_scope_404_on_non_int(
    client, survey_with_two_text_questions, owner
):
    survey, _, _ = survey_with_two_text_questions
    client.force_login(owner)
    response = client.get(
        reverse("surveys:text_responses", kwargs={"slug": survey.slug}),
        {"question": "abc"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_results_page_browse_link_uses_query_scope(client, owner):
    """The Results page "Browse responses →" link must use ``?question=`` so
    Browse text actually filters to that question, not just scrolls."""
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    q = Question.objects.create(
        survey=survey, text="Tell me", type=Question.Type.OPEN_TEXT, order=1
    )
    _new_response(q, "feedback")
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    body = response.content.decode()
    browse_url = reverse("surveys:text_responses", kwargs={"slug": survey.slug})
    assert f"{browse_url}?question={q.id}" in body
    # The old anchor-only form must not regress in.
    assert f"{browse_url}#question-{q.id}" not in body
