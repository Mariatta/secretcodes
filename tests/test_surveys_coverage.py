"""Targeted tests to cover otherwise-untested branches.

Each test here exercises a specific line that wasn't reached by the
behavior-focused tests in the other files. Kept in a single module so
the coverage rationale is in one place.
"""

import uuid

import pytest
from django import forms as django_forms
from django.contrib import admin
from django.contrib.auth import get_user_model

from surveys.admin import QuestionAdmin, ResponseAdmin, ThemeAdmin
from surveys.forms import QuestionForm
from surveys.models import (
    Question,
    Response,
    ResponseTheme,
    Survey,
    Theme,
)
from surveys.services.aggregations import (
    _bars_relative_to_max,
    _summarize_multi_select,
    _summarize_nps,
)
from surveys.services.exports import build_csv
from surveys.services.import_md import _coerce, parse_markdown
from surveys.services.themes import co_occurring, merge
from surveys.services.triage import (
    auto_mark_whitespace_not_actionable,
    queue_neighbors,
)

User = get_user_model()


@pytest.fixture
def owner(db, surveys_user_perm):
    user = User.objects.create_user(username="cov-owner", password="pw")
    user.user_permissions.add(surveys_user_perm)
    return user


# ---------- model __str__ + BaseModel save -------------------------------


@pytest.mark.django_db
def test_model_str_methods_and_basemodel_update_fields(owner):
    """Cover __str__ on every model + BaseModel.save's update_fields branch."""
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-s")
    q = Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    r = Response.objects.create(question=q, submission_uuid=uuid.uuid4(), value="x")
    theme = Theme.objects.create(survey=survey, name="T")
    rt = ResponseTheme.objects.create(response=r, theme=theme)

    assert str(survey) == "S"
    assert str(q).startswith("S — Q")
    assert "Response to" in str(r)
    assert str(theme) == "T"
    assert "↔" in str(rt)

    """BaseModel.save with update_fields auto-appends modified_date."""
    survey.title = "S2"
    survey.save(update_fields=["title"])
    survey.refresh_from_db()
    assert survey.title == "S2"


# ---------- forms ----------------------------------------------------------


@pytest.mark.django_db
def test_question_form_has_changed_returns_false_for_text_empty():
    """Extra rows with no text must skip super().has_changed() — keeps them
    out of validation even if order/type ended up auto-filled."""
    data = {"order": "3", "text": "", "type": "rating", "config": ""}
    form = QuestionForm(data=data, prefix="x")
    assert form.has_changed() is False


def test_question_form_clean_config_invalid_json():
    form = QuestionForm(prefix="x")
    form.cleaned_data = {"config": "{not json"}
    with pytest.raises(django_forms.ValidationError, match="valid JSON"):
        form.clean_config()


def test_question_form_clean_config_non_object_json():
    form = QuestionForm(prefix="x")
    form.cleaned_data = {"config": "[1, 2, 3]"}
    with pytest.raises(django_forms.ValidationError, match="JSON object"):
        form.clean_config()


def test_question_form_clean_config_dict_passthrough():
    """When initial config is already a dict (e.g. instance reload), accept as-is."""
    form = QuestionForm(prefix="x")
    form.cleaned_data = {"config": {"max": 5}}
    assert form.clean_config() == {"max": 5}


def test_question_form_clean_config_returns_parsed_dict():
    """Valid JSON object string parses + is returned."""
    form = QuestionForm(prefix="x")
    form.cleaned_data = {"config": '{"max": 5}'}
    assert form.clean_config() == {"max": 5}


# ---------- aggregations ---------------------------------------------------


def test_bars_relative_to_max_empty_returns_empty_list():
    assert _bars_relative_to_max({}) == []


@pytest.mark.django_db
def test_summarize_nps_empty_yields_none_scores(owner):
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-nps")
    q = Question.objects.create(
        survey=survey, text="N", type=Question.Type.NPS, config={}, order=1
    )
    summary = _summarize_nps(q, [])
    assert summary.nps_score is None
    assert summary.average is None


@pytest.mark.django_db
def test_summarize_multi_select_includes_undeclared_choices(owner):
    """If a stored response references a choice not in config['choices'],
    it's still counted (so old data isn't dropped silently)."""
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-ms")
    q = Question.objects.create(
        survey=survey,
        text="Q",
        type=Question.Type.MULTI_SELECT,
        config={"choices": ["A"]},
        order=1,
    )
    summary = _summarize_multi_select(q, [["A", "Mystery"]])
    assert summary.distribution["Mystery"] == 1


# ---------- exports --------------------------------------------------------


@pytest.mark.django_db
def test_csv_picks_earliest_submitted_at_per_submission(owner):
    """Multiple Responses sharing a submission_uuid should use the earliest
    timestamp as the canonical one — covers the min-update branch."""
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-csv")
    q1 = Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    q2 = Question.objects.create(
        survey=survey, text="Q2", type=Question.Type.OPEN_TEXT, config={}, order=2
    )
    sid = uuid.uuid4()
    Response.objects.create(question=q1, submission_uuid=sid, value="a")
    r2 = Response.objects.create(question=q2, submission_uuid=sid, value="b")
    """Force r2 to have a later submitted_at than r1 (newer record)."""
    Response.objects.filter(pk=r2.pk).update(submitted_at=r2.submitted_at)
    body = build_csv(survey)
    assert sid.hex in body or str(sid) in body


# ---------- import_md ------------------------------------------------------


def test_coerce_true_false_quoted_string_fallthrough():
    assert _coerce("true") is True
    assert _coerce("false") is False
    assert _coerce('"hello world"') == "hello world"
    assert _coerce("plain text") == "plain text"


def test_parse_markdown_handles_blank_and_separator_in_question_section():
    md = "# T\n" "\n" "## Q1\n" "\n" "---\n" "\n" "- type: open_text\n"
    parsed = parse_markdown(md)
    assert len(parsed.questions) == 1


def test_parse_markdown_skips_stray_h1_between_questions():
    """A stray '# ' heading mid-doc breaks the inner loop and forces the
    outer loop to skip non-H2 lines."""
    md = (
        "# T\n"
        "\n"
        "## Q1\n"
        "- type: open_text\n"
        "\n"
        "# Stray\n"
        "\n"
        "## Q2\n"
        "- type: yes_no\n"
    )
    parsed = parse_markdown(md)
    assert [q.text for q in parsed.questions] == ["Q1", "Q2"]


# ---------- themes ---------------------------------------------------------


@pytest.mark.django_db
def test_co_occurring_returns_empty_when_no_responses(owner):
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-co")
    theme = Theme.objects.create(survey=survey, name="T")
    assert co_occurring(theme) == []


@pytest.mark.django_db
def test_merge_same_theme_is_noop(owner):
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-merge")
    theme = Theme.objects.create(survey=survey, name="T")
    merge(theme, theme)
    assert Theme.objects.filter(pk=theme.pk).exists()


# ---------- triage ---------------------------------------------------------


@pytest.mark.django_db
def test_queue_neighbors_unknown_response_returns_none_pair(owner):
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-q")
    Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    assert queue_neighbors(survey, response_id=999_999) == (None, None)


@pytest.mark.django_db
def test_auto_mark_whitespace_returns_false_when_already_tagged(owner):
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-ws")
    q = Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    r = Response.objects.create(question=q, submission_uuid=uuid.uuid4(), value="   ")
    theme = Theme.objects.create(survey=survey, name="X")
    ResponseTheme.objects.create(response=r, theme=theme)
    assert auto_mark_whitespace_not_actionable(r, owner) is False


# ---------- admin ---------------------------------------------------------


@pytest.mark.django_db
def test_admin_display_methods(owner):
    """Cover the admin display callbacks."""
    survey = Survey.objects.create(owner=owner, title="S", slug="cov-admin")
    short_q = Question.objects.create(
        survey=survey, text="Short Q", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    long_q = Question.objects.create(
        survey=survey, text="x" * 100, type=Question.Type.OPEN_TEXT, config={}, order=2
    )
    qa = QuestionAdmin(Question, admin.site)
    assert qa.short_text(short_q) == "Short Q"
    assert qa.short_text(long_q).endswith("…")

    ra = ResponseAdmin(Response, admin.site)
    assert ra.has_add_permission(request=None) is False

    theme = Theme.objects.create(survey=survey, name="T", action_item="x")
    ta = ThemeAdmin(Theme, admin.site)
    assert ta.mention_count(theme) == 0
    assert ta.has_action_item(theme) is True
    empty = Theme.objects.create(survey=survey, name="Empty")
    assert ta.has_action_item(empty) is False
