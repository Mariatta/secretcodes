import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from surveys.models import Question, Survey
from surveys.services.import_md import (
    MarkdownImportError,
    import_survey,
    parse_markdown,
)


@pytest.fixture
def owner(db, surveys_user_perm, surveys_create_perm):
    user = get_user_model().objects.create_user(username="owner", password="pw")
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


SAMPLE_MD = textwrap.dedent("""
    # Post-event feedback

    slug: post-event
    status: draft

    ## How would you rate the event?
    - type: rating
    - max: 5
    - labels: {"1": "Poor", "5": "Excellent"}

    ## Which sessions did you attend?
    - type: multi_select
    - choices: ["Talks", "Workshops", "Hallway"]
    - required: false

    ## How likely are you to recommend us?
    - type: nps

    ## Anything else?
    - type: open_text
    - required: false

    ## Would you come again?
    - type: yes_no
    """).strip()


def test_parse_extracts_title_slug_status():
    parsed = parse_markdown(SAMPLE_MD)
    assert parsed.title == "Post-event feedback"
    assert parsed.slug == "post-event"
    assert parsed.status == "draft"


def test_parse_extracts_questions_in_order():
    parsed = parse_markdown(SAMPLE_MD)
    types = [q.type for q in parsed.questions]
    assert types == ["rating", "multi_select", "nps", "open_text", "yes_no"]


def test_parse_question_config_with_json_values():
    parsed = parse_markdown(SAMPLE_MD)
    rating = parsed.questions[0]
    assert rating.config == {"max": 5, "labels": {"1": "Poor", "5": "Excellent"}}
    multi = parsed.questions[1]
    assert multi.config == {"choices": ["Talks", "Workshops", "Hallway"]}


def test_parse_required_default_true():
    parsed = parse_markdown(SAMPLE_MD)
    rating = parsed.questions[0]
    assert rating.required is True


def test_parse_required_false_when_set():
    parsed = parse_markdown(SAMPLE_MD)
    multi = parsed.questions[1]
    assert multi.required is False


def test_parse_no_h1_raises():
    md = "## Just a question\n- type: open_text\n"
    with pytest.raises(MarkdownImportError, match="must start with"):
        parse_markdown(md)


def test_parse_no_questions_raises():
    md = "# Survey title\nslug: x\n"
    with pytest.raises(MarkdownImportError, match="at least one"):
        parse_markdown(md)


def test_parse_missing_type_raises():
    md = textwrap.dedent("""
        # T
        ## A question?
        - max: 5
        """).strip()
    with pytest.raises(MarkdownImportError, match="missing a 'type:'"):
        parse_markdown(md)


def test_parse_invalid_type_raises():
    md = textwrap.dedent("""
        # T
        ## A question?
        - type: nonsense
        """).strip()
    with pytest.raises(MarkdownImportError, match="invalid type"):
        parse_markdown(md)


def test_parse_invalid_json_raises():
    md = textwrap.dedent("""
        # T
        ## A question?
        - type: multi_select
        - choices: [not, json
        """).strip()
    with pytest.raises(MarkdownImportError, match="Invalid JSON"):
        parse_markdown(md)


def test_parse_invalid_status_raises():
    md = textwrap.dedent("""
        # T
        slug: t
        status: nope

        ## Q
        - type: open_text
        """).strip()
    with pytest.raises(MarkdownImportError, match="status must be"):
        parse_markdown(md)


def test_parse_slug_defaults_to_slugified_title():
    md = textwrap.dedent("""
        # Post-event Feedback Round 2!

        ## Q
        - type: open_text
        """).strip()
    parsed = parse_markdown(md)
    assert parsed.slug == "post-event-feedback-round-2"


def test_parse_status_defaults_to_draft():
    md = textwrap.dedent("""
        # T

        ## Q
        - type: open_text
        """).strip()
    parsed = parse_markdown(md)
    assert parsed.status == "draft"


def test_parse_handles_blank_lines_and_separator_rules():
    md = textwrap.dedent("""
        # Title

        slug: t

        ---

        ## Q1
        - type: open_text

        ---

        ## Q2
        - type: yes_no
        """).strip()
    parsed = parse_markdown(md)
    assert len(parsed.questions) == 2


@pytest.mark.django_db
def test_import_creates_survey_and_questions(owner):
    parsed = parse_markdown(SAMPLE_MD)
    survey = import_survey(parsed, owner=owner)
    assert survey.owner == owner
    assert survey.slug == "post-event"
    assert survey.questions.count() == 5
    rating = survey.questions.get(order=1)
    assert rating.type == Question.Type.RATING
    assert rating.config == {"max": 5, "labels": {"1": "Poor", "5": "Excellent"}}
    multi = survey.questions.get(order=2)
    assert multi.required is False


@pytest.mark.django_db
def test_import_rejects_existing_slug(owner):
    Survey.objects.create(owner=owner, title="X", slug="post-event")
    parsed = parse_markdown(SAMPLE_MD)
    with pytest.raises(MarkdownImportError, match="already exists"):
        import_survey(parsed, owner=owner)


@pytest.mark.django_db
def test_import_view_login_required(client):
    response = client.get(reverse("surveys:import"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_import_view_renders_form(client, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:import"))
    assert response.status_code == 200
    assert b"Import a survey" in response.content
    assert b"Markdown format" in response.content


@pytest.mark.django_db
def test_import_view_creates_survey_from_upload(client, owner):
    client.force_login(owner)
    upload = SimpleUploadedFile(
        "survey.md", SAMPLE_MD.encode("utf-8"), content_type="text/markdown"
    )
    response = client.post(reverse("surveys:import"), {"markdown_file": upload})
    assert response.status_code == 302
    survey = Survey.objects.get(slug="post-event")
    assert response.url == reverse("surveys:edit", kwargs={"slug": "post-event"})
    assert survey.questions.count() == 5


@pytest.mark.django_db
def test_import_view_invalid_markdown_shows_error(client, owner):
    client.force_login(owner)
    upload = SimpleUploadedFile(
        "bad.md",
        b"## just a question\n- type: open_text\n",
        content_type="text/markdown",
    )
    response = client.post(reverse("surveys:import"), {"markdown_file": upload})
    assert response.status_code == 200
    assert b"must start with" in response.content
    assert Survey.objects.count() == 0


@pytest.mark.django_db
def test_import_view_existing_slug_shows_error(client, owner):
    Survey.objects.create(owner=owner, title="X", slug="post-event")
    client.force_login(owner)
    upload = SimpleUploadedFile(
        "x.md", SAMPLE_MD.encode("utf-8"), content_type="text/markdown"
    )
    response = client.post(reverse("surveys:import"), {"markdown_file": upload})
    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Survey.objects.count() == 1  # didn't create a duplicate


@pytest.mark.django_db
def test_import_view_non_utf8_file_shows_error(client, owner):
    client.force_login(owner)
    upload = SimpleUploadedFile(
        "x.md",
        b"\xff\xfe# T\n## Q\n- type: open_text\n",
        content_type="text/markdown",
    )
    response = client.post(reverse("surveys:import"), {"markdown_file": upload})
    assert response.status_code == 200
    assert b"UTF-8" in response.content


@pytest.mark.django_db
def test_dashboard_has_import_link(client, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert reverse("surveys:import").encode() in response.content
