import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from surveys.models import Question, Response, Survey


@pytest.fixture
def owner(db, surveys_user_perm, surveys_create_perm):
    user = get_user_model().objects.create_user(username="owner", password="pw")
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


@pytest.fixture
def published_survey(owner):
    """A published survey with one of every question type."""
    survey = Survey.objects.create(
        owner=owner,
        title="Post-event feedback",
        slug="post-event",
        status=Survey.Status.PUBLISHED,
    )
    Question.objects.create(
        survey=survey,
        text="How would you rate the event?",
        type=Question.Type.RATING,
        config={"max": 5},
        order=1,
    )
    Question.objects.create(
        survey=survey,
        text="Which tracks did you attend?",
        type=Question.Type.MULTI_SELECT,
        config={"choices": ["Talks", "Workshops", "Hallway"]},
        required=False,
        order=2,
    )
    Question.objects.create(
        survey=survey,
        text="How likely are you to recommend us?",
        type=Question.Type.NPS,
        config={},
        order=3,
    )
    Question.objects.create(
        survey=survey,
        text="Anything else?",
        type=Question.Type.OPEN_TEXT,
        config={},
        required=False,
        order=4,
    )
    Question.objects.create(
        survey=survey,
        text="Would you come again?",
        type=Question.Type.YES_NO,
        config={},
        order=5,
    )
    return survey


@pytest.mark.django_db
def test_get_renders_published_survey(client, published_survey):
    url = reverse("surveys:respond", kwargs={"slug": published_survey.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert b"Post-event feedback" in response.content
    assert b"No login. No cookies. No tracking." in response.content
    assert b"How would you rate the event?" in response.content


@pytest.mark.django_db
def test_get_returns_404_for_draft_survey(client, owner):
    Survey.objects.create(
        owner=owner, title="Draft", slug="draft", status=Survey.Status.DRAFT
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "draft"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_get_renders_friendly_page_for_closed_survey(client, owner):
    """Closed surveys return 200 with a "this is closed" page, not 404 —
    a respondent following an old link deserves an explanation."""
    Survey.objects.create(
        owner=owner, title="Closed", slug="closed", status=Survey.Status.CLOSED
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "closed"}))
    assert response.status_code == 200
    assert b"This survey is closed." in response.content
    """The form must not render — closed surveys can't accept new responses."""
    assert b"Submit feedback" not in response.content


@pytest.mark.django_db
def test_post_to_closed_survey_does_not_record_response(client, owner):
    survey = Survey.objects.create(
        owner=owner, title="Closed", slug="closed", status=Survey.Status.CLOSED
    )
    Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, order=1
    )
    http_response = client.post(
        reverse("surveys:respond", kwargs={"slug": "closed"}),
        {"q1": "trying anyway"},
    )
    assert http_response.status_code == 200
    assert b"This survey is closed." in http_response.content
    assert Response.objects.count() == 0


@pytest.mark.django_db
def test_get_returns_404_for_unknown_slug(client):
    response = client.get(reverse("surveys:respond", kwargs={"slug": "nope"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_post_valid_creates_responses_with_shared_submission_uuid(
    client, published_survey
):
    questions = {q.type: q for q in published_survey.questions.all()}
    payload = {
        f"q{questions[Question.Type.RATING].id}": "4",
        f"q{questions[Question.Type.MULTI_SELECT].id}": ["Talks", "Hallway"],
        f"q{questions[Question.Type.NPS].id}": "9",
        f"q{questions[Question.Type.OPEN_TEXT].id}": "Loved the hallway track.",
        f"q{questions[Question.Type.YES_NO].id}": "yes",
    }
    url = reverse("surveys:respond", kwargs={"slug": published_survey.slug})
    response = client.post(url, payload)
    assert response.status_code == 302
    assert response.url == reverse(
        "surveys:done", kwargs={"slug": published_survey.slug}
    )
    rows = Response.objects.all()
    assert rows.count() == 5
    submission_uuids = {r.submission_uuid for r in rows}
    assert len(submission_uuids) == 1
    by_type = {r.question.type: r.value for r in rows}
    assert by_type[Question.Type.RATING] == 4
    assert sorted(by_type[Question.Type.MULTI_SELECT]) == ["Hallway", "Talks"]
    assert by_type[Question.Type.NPS] == 9
    assert by_type[Question.Type.OPEN_TEXT] == "Loved the hallway track."
    assert by_type[Question.Type.YES_NO] is True


@pytest.mark.django_db
def test_post_skips_optional_blank_fields(client, published_survey):
    questions = {q.type: q for q in published_survey.questions.all()}
    payload = {
        f"q{questions[Question.Type.RATING].id}": "3",
        f"q{questions[Question.Type.NPS].id}": "7",
        f"q{questions[Question.Type.YES_NO].id}": "no",
    }
    url = reverse("surveys:respond", kwargs={"slug": published_survey.slug})
    response = client.post(url, payload)
    assert response.status_code == 302
    rows = Response.objects.all()
    assert rows.count() == 3
    types_recorded = {r.question.type for r in rows}
    assert Question.Type.MULTI_SELECT not in types_recorded
    assert Question.Type.OPEN_TEXT not in types_recorded


@pytest.mark.django_db
def test_post_invalid_rerenders_with_errors(client, published_survey):
    """A required RATING omitted should not redirect or write rows."""
    url = reverse("surveys:respond", kwargs={"slug": published_survey.slug})
    response = client.post(url, {})
    assert response.status_code == 200
    assert Response.objects.count() == 0
    assert b"This field is required" in response.content


@pytest.mark.django_db
def test_post_anonymity_no_user_fk(client, published_survey, owner):
    client.force_login(owner)
    questions = {q.type: q for q in published_survey.questions.all()}
    client.post(
        reverse("surveys:respond", kwargs={"slug": published_survey.slug}),
        {
            f"q{questions[Question.Type.RATING].id}": "5",
            f"q{questions[Question.Type.NPS].id}": "10",
            f"q{questions[Question.Type.YES_NO].id}": "yes",
        },
    )
    """Even with an authenticated client, no Response field references the user."""
    row = Response.objects.first()
    assert not any(
        f.name in ("user", "respondent", "owner", "ip_address", "user_agent")
        for f in row._meta.get_fields()
    )


@pytest.mark.django_db
def test_rating_choices_render_labels_when_provided(client, owner):
    """Custom labels in config show up next to the score."""
    survey = Survey.objects.create(
        owner=owner, title="L", slug="l", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Rate it",
        type=Question.Type.RATING,
        config={"max": 5, "labels": {"1": "Poor", "5": "Excellent"}},
        order=1,
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "l"}))
    assert response.status_code == 200
    assert b"Poor" in response.content
    assert b"Excellent" in response.content
    assert b">2<" in response.content  # unlabeled score still renders bare
    assert b"1 \xe2\x80\x94" not in response.content  # no "1 — Poor" form


@pytest.mark.django_db
def test_rating_choices_unlabeled_when_no_labels(client, owner):
    """No labels in config = bare numbers."""
    survey = Survey.objects.create(
        owner=owner, title="U", slug="u", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Rate",
        type=Question.Type.RATING,
        config={"max": 5},
        order=1,
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "u"}))
    assert response.status_code == 200
    assert b"1 \xe2\x80\x94" not in response.content  # no "1 —" labeled choice


@pytest.mark.django_db
def test_nps_choices_can_carry_labels(client, owner):
    """NPS endpoints can be named via the same labels mechanism."""
    survey = Survey.objects.create(
        owner=owner, title="N", slug="n", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Recommend?",
        type=Question.Type.NPS,
        config={"labels": {"0": "Not at all", "10": "Extremely"}},
        order=1,
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "n"}))
    assert response.status_code == 200
    assert b"Not at all" in response.content
    assert b"Extremely" in response.content
    assert b"0 \xe2\x80\x94" not in response.content


@pytest.mark.django_db
def test_optional_questions_show_optional_label(client, owner):
    survey = Survey.objects.create(
        owner=owner, title="O", slug="o", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Required Q",
        type=Question.Type.OPEN_TEXT,
        order=1,
        required=True,
    )
    Question.objects.create(
        survey=survey,
        text="Optional Q",
        type=Question.Type.OPEN_TEXT,
        order=2,
        required=False,
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "o"}))
    assert response.status_code == 200
    """Required Q has no label; Optional Q is marked."""
    content = response.content.decode("utf-8")
    optional_section = content.split("Optional Q")[1]
    required_section = content.split("Required Q")[1].split("Optional Q")[0]
    assert "(Optional)" in optional_section
    assert "(Optional)" not in required_section


@pytest.mark.django_db
def test_yes_no_renders_as_button_toggle(client, owner):
    survey = Survey.objects.create(
        owner=owner, title="Y", slug="y", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey, text="Yn?", type=Question.Type.YES_NO, order=1
    )
    response = client.get(reverse("surveys:respond", kwargs={"slug": "y"}))
    assert response.status_code == 200
    assert b"yesno-btn-group" in response.content
    assert b"yesno-yes" in response.content
    assert b"yesno-no" in response.content


@pytest.mark.django_db
def test_rating_field_renders_with_star_wrapper(client, owner):
    """Rating questions get the star-rating-field wrapper so CSS can style
    them as stars; non-rating types do not."""
    survey = Survey.objects.create(
        owner=owner, title="S", slug="s", status=Survey.Status.PUBLISHED
    )
    Question.objects.create(
        survey=survey,
        text="Rate",
        type=Question.Type.RATING,
        config={"max": 5},
        order=1,
    )
    Question.objects.create(survey=survey, text="Nps?", type=Question.Type.NPS, order=2)
    response = client.get(reverse("surveys:respond", kwargs={"slug": "s"}))
    assert response.status_code == 200
    assert b"star-rating-field" in response.content
    """NPS uses default wrapper, not star-rating-field around it."""
    nps_section = (
        response.content.split(b"Nps?")[1] if b"Nps?" in response.content else b""
    )
    assert b"star-rating-field" not in nps_section


@pytest.mark.django_db
def test_done_page_renders_for_published(client, published_survey):
    url = reverse("surveys:done", kwargs={"slug": published_survey.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert b"Thanks for your feedback" in response.content


@pytest.mark.django_db
def test_done_page_404_for_draft(client, owner):
    Survey.objects.create(owner=owner, title="D", slug="d", status=Survey.Status.DRAFT)
    response = client.get(reverse("surveys:done", kwargs={"slug": "d"}))
    assert response.status_code == 404
