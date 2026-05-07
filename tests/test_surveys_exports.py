import csv
import io
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
from surveys.services.exports import (
    build_action_items_markdown,
    build_csv,
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


def _q(survey, type_, order, text="Q", config=None):
    return Question.objects.create(
        survey=survey, text=text, type=type_, config=config or {}, order=order
    )


def _submit(question_to_value: dict[Question, object]) -> uuid.UUID:
    sid = uuid.uuid4()
    for q, v in question_to_value.items():
        Response.objects.create(question=q, submission_uuid=sid, value=v)
    return sid


def _read_csv(body: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body)))


@pytest.mark.django_db
def test_csv_header_includes_question_text(survey):
    _q(survey, Question.Type.RATING, 1, text="Rate it")
    _q(survey, Question.Type.OPEN_TEXT, 2, text="Anything else?")
    rows = _read_csv(build_csv(survey))
    assert rows[0] == ["submission_uuid", "submitted_at", "Rate it", "Anything else?"]


@pytest.mark.django_db
def test_csv_one_row_per_submission(survey):
    rating = _q(survey, Question.Type.RATING, 1, text="Rate")
    text = _q(survey, Question.Type.OPEN_TEXT, 2, text="Why")
    _submit({rating: 5, text: "great"})
    _submit({rating: 3, text: "meh"})
    rows = _read_csv(build_csv(survey))
    assert len(rows) == 3  # header + 2 submissions
    """Rate column should have 5 / 3, Why column should have great / meh."""
    rate_col = [r[2] for r in rows[1:]]
    why_col = [r[3] for r in rows[1:]]
    assert sorted(rate_col) == ["3", "5"]
    assert sorted(why_col) == ["great", "meh"]


@pytest.mark.django_db
def test_csv_multi_select_join_with_semicolons(survey):
    ms = _q(
        survey,
        Question.Type.MULTI_SELECT,
        1,
        text="Pick",
        config={"choices": ["A", "B", "C"]},
    )
    _submit({ms: ["A", "C"]})
    rows = _read_csv(build_csv(survey))
    assert rows[1][2] == "A; C"


@pytest.mark.django_db
def test_csv_yes_no_renders_as_words(survey):
    yn = _q(survey, Question.Type.YES_NO, 1, text="Again?")
    _submit({yn: True})
    _submit({yn: False})
    rows = _read_csv(build_csv(survey))
    cells = sorted(row[2] for row in rows[1:])
    assert cells == ["No", "Yes"]


@pytest.mark.django_db
def test_csv_missing_answer_renders_empty(survey):
    a = _q(survey, Question.Type.RATING, 1, text="A")
    _q(survey, Question.Type.OPEN_TEXT, 2, text="B")
    _submit({a: 5})  # no B
    rows = _read_csv(build_csv(survey))
    assert rows[1][2] == "5"
    assert rows[1][3] == ""


@pytest.mark.django_db
def test_csv_empty_survey_returns_only_header(survey):
    _q(survey, Question.Type.OPEN_TEXT, 1, text="Q")
    rows = _read_csv(build_csv(survey))
    assert len(rows) == 1


@pytest.mark.django_db
def test_csv_view_requires_owner(client, survey, other_user):
    client.force_login(other_user)
    response = client.get(reverse("surveys:export_csv", kwargs={"slug": survey.slug}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_csv_view_login_required(client, survey):
    response = client.get(reverse("surveys:export_csv", kwargs={"slug": survey.slug}))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_csv_view_renders_with_attachment_disposition(client, survey, owner):
    _q(survey, Question.Type.OPEN_TEXT, 1)
    client.force_login(owner)
    response = client.get(reverse("surveys:export_csv", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert "text/csv" in response["Content-Type"]
    assert "attachment" in response["Content-Disposition"]
    assert "secretcodes-s-responses.csv" in response["Content-Disposition"]


@pytest.mark.django_db
def test_markdown_with_no_action_items(survey):
    body = build_action_items_markdown(survey)
    assert "No action items" in body


@pytest.mark.django_db
def test_markdown_includes_action_items(survey, owner):
    Theme.objects.create(
        survey=survey,
        name="Scheduling",
        tag="ops",
        action_item="Add 30-min breaks between tracks.",
        priority=Theme.Priority.HIGH,
        status=Theme.Status.OPEN,
    )
    body = build_action_items_markdown(survey)
    assert "# S — Action Items" in body
    assert "## Scheduling" in body
    assert "`ops`" in body
    assert "**Priority:** High" in body
    assert "**Status:** Open" in body
    assert "Add 30-min breaks between tracks." in body


@pytest.mark.django_db
def test_markdown_orders_open_high_first(survey):
    Theme.objects.create(
        survey=survey,
        name="A-resolved",
        action_item="x",
        status=Theme.Status.RESOLVED,
        priority=Theme.Priority.HIGH,
    )
    Theme.objects.create(
        survey=survey,
        name="B-open-low",
        action_item="x",
        status=Theme.Status.OPEN,
        priority=Theme.Priority.LOW,
    )
    Theme.objects.create(
        survey=survey,
        name="C-open-high",
        action_item="x",
        status=Theme.Status.OPEN,
        priority=Theme.Priority.HIGH,
    )
    body = build_action_items_markdown(survey)
    pos_a = body.index("A-resolved")
    pos_b = body.index("B-open-low")
    pos_c = body.index("C-open-high")
    assert pos_c < pos_b < pos_a


@pytest.mark.django_db
def test_markdown_includes_representative_quote(survey, owner):
    q = _q(survey, Question.Type.OPEN_TEXT, 1, text="Anything?")
    r = Response.objects.create(
        question=q, submission_uuid=uuid.uuid4(), value="The pull quote."
    )
    theme = Theme.objects.create(
        survey=survey,
        name="X",
        action_item="y",
    )
    ResponseTheme.objects.create(
        response=r, theme=theme, tagged_by=owner, is_representative=True
    )
    body = build_action_items_markdown(survey)
    assert "> The pull quote." in body


@pytest.mark.django_db
def test_markdown_excludes_themes_without_action_item(survey):
    Theme.objects.create(survey=survey, name="Drafted", action_item="")
    Theme.objects.create(survey=survey, name="Done", action_item="ship it")
    body = build_action_items_markdown(survey)
    assert "## Drafted" not in body
    assert "## Done" in body


@pytest.mark.django_db
def test_md_view_requires_owner(client, survey, other_user):
    client.force_login(other_user)
    response = client.get(
        reverse("surveys:export_action_items", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_md_view_attachment_disposition(client, survey, owner):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:export_action_items", kwargs={"slug": survey.slug})
    )
    assert response.status_code == 200
    assert "text/markdown" in response["Content-Type"]
    assert "secretcodes-s-action-items.md" in response["Content-Disposition"]
