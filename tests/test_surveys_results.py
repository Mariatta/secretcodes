import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from surveys.models import Question, Response, Survey
from surveys.services.aggregations import aggregate_survey


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


def _make_survey(owner, status=Survey.Status.PUBLISHED):
    return Survey.objects.create(owner=owner, title="S", slug="s", status=status)


def _q(survey, type_, order, config=None):
    return Question.objects.create(
        survey=survey, text=f"Q{order}", type=type_, config=config or {}, order=order
    )


def _submit(question_to_value: dict[Question, object]) -> uuid.UUID:
    """Create one submission worth of Response rows under a shared uuid."""
    sid = uuid.uuid4()
    for q, v in question_to_value.items():
        Response.objects.create(question=q, submission_uuid=sid, value=v)
    return sid


@pytest.mark.django_db
def test_empty_survey_aggregates_to_zeros(owner):
    survey = _make_survey(owner)
    _q(survey, Question.Type.RATING, 1)
    agg = aggregate_survey(survey)
    assert agg.submission_count == 0
    assert agg.completion_rate is None
    assert agg.average_rating is None
    assert agg.summaries[0].response_count == 0


@pytest.mark.django_db
def test_rating_distribution_and_average(owner):
    survey = _make_survey(owner)
    rating = _q(survey, Question.Type.RATING, 1, {"max": 5})
    for v in [5, 5, 4, 3, 5]:
        _submit({rating: v})
    agg = aggregate_survey(survey)
    summary = agg.summaries[0]
    assert summary.distribution == {1: 0, 2: 0, 3: 1, 4: 1, 5: 3}
    assert summary.average == pytest.approx(4.4)
    assert agg.average_rating == pytest.approx(4.4)
    by_label = {b.label: b for b in summary.bars}
    assert by_label["5"].count == 3
    assert by_label["5"].width_pct == 100
    assert by_label["3"].width_pct == round(100 / 3)


@pytest.mark.django_db
def test_nps_score_formula(owner):
    """10 responses: 6 promoters (9-10), 2 passives (7-8), 2 detractors (0-6).
    NPS = (60% - 20%) = 40."""
    survey = _make_survey(owner)
    nps = _q(survey, Question.Type.NPS, 1)
    for v in [10, 10, 10, 10, 9, 9, 8, 7, 6, 0]:
        _submit({nps: v})
    agg = aggregate_survey(survey)
    summary = agg.summaries[0]
    assert summary.nps_score == pytest.approx(40.0)
    assert summary.average == pytest.approx(7.9)


@pytest.mark.django_db
def test_multi_select_counts(owner):
    survey = _make_survey(owner)
    ms = _q(
        survey,
        Question.Type.MULTI_SELECT,
        1,
        {"choices": ["A", "B", "C"]},
    )
    _submit({ms: ["A", "B"]})
    _submit({ms: ["A"]})
    _submit({ms: ["B", "C"]})
    agg = aggregate_survey(survey)
    summary = agg.summaries[0]
    assert summary.distribution == {"A": 2, "B": 2, "C": 1}
    assert summary.response_count == 3
    by_label = {b.label: b for b in summary.bars}
    assert by_label["A"].width_pct == round(2 * 100 / 3)


@pytest.mark.django_db
def test_yes_no_counts(owner):
    survey = _make_survey(owner)
    yn = _q(survey, Question.Type.YES_NO, 1)
    for v in [True, True, True, False]:
        _submit({yn: v})
    agg = aggregate_survey(survey)
    summary = agg.summaries[0]
    assert summary.distribution == {"Yes": 3, "No": 1}
    assert summary.response_count == 4


@pytest.mark.django_db
def test_open_text_count_excludes_blank_strings(owner):
    survey = _make_survey(owner)
    ot = _q(survey, Question.Type.OPEN_TEXT, 1)
    _submit({ot: "Loved it."})
    _submit({ot: "Great event."})
    _submit({ot: "   "})
    agg = aggregate_survey(survey)
    summary = agg.summaries[0]
    assert summary.open_text_count == 2
    assert summary.response_count == 2


@pytest.mark.django_db
def test_completion_rate_includes_unanswered(owner):
    """3 submissions × 2 questions = 6 cells, 5 responses → 5/6."""
    survey = _make_survey(owner)
    rating = _q(survey, Question.Type.RATING, 1)
    open_text = _q(survey, Question.Type.OPEN_TEXT, 2)
    _submit({rating: 5, open_text: "x"})
    _submit({rating: 4, open_text: "y"})
    _submit({rating: 3})
    agg = aggregate_survey(survey)
    assert agg.submission_count == 3
    assert agg.completion_rate == pytest.approx(5 / 6)


@pytest.mark.django_db
def test_results_view_requires_login(client, owner):
    survey = _make_survey(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_results_view_requires_ownership(client, owner, other_user):
    survey = _make_survey(other_user)
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_results_view_renders_for_owner(client, owner):
    survey = _make_survey(owner)
    rating = _q(survey, Question.Type.RATING, 1, {"max": 5})
    _submit({rating: 5})
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"avg rating" in response.content
    assert b"Q1" in response.content


@pytest.mark.django_db
def test_results_view_open_text_callout(client, owner):
    survey = _make_survey(owner)
    ot = _q(survey, Question.Type.OPEN_TEXT, 1)
    _submit({ot: "feedback"})
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"open-text" in response.content
    assert b"response" in response.content
    assert b"group into themes" in response.content
    assert b'class="nudge"' in response.content


@pytest.mark.django_db
def test_results_view_shows_status_pill(client, owner):
    """Top-right status pill: green=Live, amber=Draft, red=Closed."""
    Survey.objects.create(
        owner=owner, title="P", slug="p", status=Survey.Status.PUBLISHED
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": "p"}))
    assert response.status_code == 200
    assert b'class="status-pill status-published"' in response.content
    assert b"Live" in response.content


@pytest.mark.django_db
def test_results_view_status_pill_for_draft(client, owner):
    Survey.objects.create(owner=owner, title="D", slug="d", status=Survey.Status.DRAFT)
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": "d"}))
    assert response.status_code == 200
    assert b'class="status-pill status-draft"' in response.content


@pytest.mark.django_db
def test_results_view_renders_type_pills(client, owner):
    """Each question card shows a colored type pill in its header."""
    survey = _make_survey(owner)
    _q(survey, Question.Type.RATING, 1, {"max": 5})
    _q(survey, Question.Type.OPEN_TEXT, 2)
    client.force_login(owner)
    response = client.get(reverse("surveys:results", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'class="type-pill rating"' in response.content
    assert b'class="type-pill open_text"' in response.content
