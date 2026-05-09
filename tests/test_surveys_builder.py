import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from surveys.models import (
    QUESTION_HARD_LIMIT,
    QUESTION_WARN_THRESHOLD,
    Question,
    Survey,
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


def _management(prefix, total=0):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


@pytest.mark.django_db
def test_dashboard_renders_landing_for_anonymous(client):
    """Anonymous users see the public landing, not a login redirect."""
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Anonymous feedback" in response.content
    assert b"private use" in response.content


@pytest.mark.django_db
def test_dashboard_renders_landing_for_logged_in_without_permission(client):
    """Authenticated users without access_surveys see the landing too —
    same gate as the expenses app."""
    user = get_user_model().objects.create_user(username="lurker", password="pw")
    client.force_login(user)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Anonymous feedback" in response.content


@pytest.mark.django_db
def test_creator_views_redirect_logged_in_without_permission(client):
    """user_passes_test on the creator views redirects to login when
    the user lacks access_surveys."""
    user = get_user_model().objects.create_user(username="lurker", password="pw")
    client.force_login(user)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_dashboard_landing_has_no_cta(client):
    """Landing should not push respondents toward sign-in."""
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Sign in" not in response.content
    assert b"sign in" not in response.content


@pytest.mark.django_db
def test_dashboard_shows_only_own_surveys(client, owner, other_user):
    Survey.objects.create(owner=owner, title="Mine", slug="mine")
    Survey.objects.create(owner=other_user, title="Theirs", slug="theirs")
    client.force_login(owner)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Mine" in response.content
    assert b"Theirs" not in response.content


@pytest.mark.django_db
def test_new_survey_renders_for_logged_in(client, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 200
    assert b"New survey" in response.content


@pytest.mark.django_db
def test_new_survey_creates_survey_and_questions(client, owner):
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "Post-event feedback",
        "slug": "post-event",
        "status": "draft",
        **_management(prefix, total=2),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Rate the event",
        f"{prefix}-0-type": "rating",
        f"{prefix}-0-config": '{"max": 5}',
        f"{prefix}-1-order": "2",
        f"{prefix}-1-text": "Anything else?",
        f"{prefix}-1-type": "open_text",
        f"{prefix}-1-config": "",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    survey = Survey.objects.get(slug="post-event")
    assert survey.owner == owner
    assert survey.status == Survey.Status.DRAFT
    assert survey.questions.count() == 2
    rating = survey.questions.get(order=1)
    assert rating.type == Question.Type.RATING
    assert rating.config == {"max": 5}
    open_text = survey.questions.get(order=2)
    assert open_text.config == {}


@pytest.mark.django_db
def test_edit_requires_owner(client, owner, other_user):
    survey = Survey.objects.create(owner=other_user, title="Theirs", slug="theirs")
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_edit_renders_for_owner(client, owner):
    survey = Survey.objects.create(owner=owner, title="Mine", slug="mine")
    Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"Edit survey" in response.content


@pytest.mark.django_db
def test_edit_publishes_survey(client, owner):
    survey = Survey.objects.create(
        owner=owner, title="Mine", slug="mine", status=Survey.Status.DRAFT
    )
    q = Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "Mine",
        "slug": "mine",
        "status": "published",
        **_management(prefix, total=1),
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-0-id": str(q.id),
        f"{prefix}-0-survey": str(survey.id),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Q1",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
    }
    response = client.post(
        reverse("surveys:edit", kwargs={"slug": survey.slug}), payload
    )
    assert response.status_code == 302
    survey.refresh_from_db()
    assert survey.status == Survey.Status.PUBLISHED


@pytest.mark.django_db
def test_edit_deletes_question(client, owner):
    survey = Survey.objects.create(owner=owner, title="Mine", slug="mine")
    q = Question.objects.create(
        survey=survey, text="Doomed", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "Mine",
        "slug": "mine",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-0-id": str(q.id),
        f"{prefix}-0-survey": str(survey.id),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Doomed",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
        f"{prefix}-0-DELETE": "on",
    }
    response = client.post(
        reverse("surveys:edit", kwargs={"slug": survey.slug}), payload
    )
    assert response.status_code == 302
    assert survey.questions.count() == 0


@pytest.mark.django_db
def test_invalid_json_config_rejected(client, owner):
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "T",
        "slug": "t",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Q1",
        f"{prefix}-0-type": "rating",
        f"{prefix}-0-config": "not json",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 200
    assert Survey.objects.count() == 0
    assert b"valid JSON" in response.content


@pytest.mark.django_db
def test_duplicate_order_rejected(client, owner):
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "T",
        "slug": "t",
        "status": "draft",
        **_management(prefix, total=2),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "First",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
        f"{prefix}-1-order": "1",
        f"{prefix}-1-text": "Also first",
        f"{prefix}-1-type": "open_text",
        f"{prefix}-1-config": "",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 200
    assert Survey.objects.count() == 0
    assert b"duplicate" in response.content.lower()


@pytest.mark.django_db
def test_edit_save_no_changes_does_not_create_empty_questions(client, owner):
    """Regression: editing without touching extras must not create empty rows.

    The type select's first option is a blank placeholder, so a browser
    submit of an untouched extra row carries ``type=""`` — which combined
    with the other empty fields makes ``has_changed()`` return False, and
    the form is skipped.
    """
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    q = Question.objects.create(
        survey=survey,
        text="Existing",
        type=Question.Type.OPEN_TEXT,
        config={},
        order=1,
    )
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "X",
        "slug": "x",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-0-id": str(q.id),
        f"{prefix}-0-survey": str(survey.id),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Existing",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
    }
    response = client.post(
        reverse("surveys:edit", kwargs={"slug": survey.slug}), payload
    )
    assert response.status_code == 302
    assert survey.questions.count() == 1


@pytest.mark.django_db
def test_builder_type_renders_as_pill_radios(client, owner):
    """Type field is now a row of selectable colored pills, not a select."""
    client.force_login(owner)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 200
    assert b"type-pill-btn-group" in response.content
    assert b"type-pill-btn-rating" in response.content
    assert b"type-pill-btn-multi_select" in response.content
    assert b"type-pill-btn-nps" in response.content
    assert b"type-pill-btn-open_text" in response.content
    assert b"type-pill-btn-yes_no" in response.content


@pytest.mark.django_db
def test_existing_row_renders_delete_input_for_js_toggling(client, owner):
    """The Remove button toggles a hidden DELETE checkbox via JS — the
    input must actually exist in the rendered form for an existing row."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'name="questions-0-DELETE"' in response.content


@pytest.mark.django_db
def test_builder_renders_empty_form_template_for_js(client, owner):
    """Builder must render the formset.empty_form inside a <template> so
    the Add-question JS can clone it."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, config={}, order=1
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'id="question-template"' in response.content
    assert b"__prefix__" in response.content
    assert b'id="add-question"' in response.content


@pytest.mark.django_db
def test_builder_starts_empty_for_new_survey(client, owner):
    """No auto-extras: a new survey form has zero question rows by default."""
    client.force_login(owner)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 200
    assert b'id="add-question"' in response.content
    assert b'name="questions-TOTAL_FORMS" value="0"' in response.content


@pytest.mark.django_db
def test_builder_renders_status_button_group(client, owner):
    """Status is a btn-check radio group (not a select), with the three options."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"status-btn-group" in response.content
    assert b'class="btn-check"' in response.content
    assert b"status-published" in response.content
    assert b"status-draft" in response.content
    assert b"status-closed" in response.content


@pytest.mark.django_db
def test_builder_renders_drag_handle_and_sortable_js(client, owner):
    """Drag handle on each row + Sortable.js loaded for the reorder UX."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, order=1
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b"drag-handle" in response.content
    assert b"Sortable.min.js" in response.content


@pytest.mark.django_db
def test_order_field_renders_as_hidden_input(client, owner):
    """Order is set by JS now, so the field is hidden in the form."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    Question.objects.create(
        survey=survey, text="Q1", type=Question.Type.OPEN_TEXT, order=1
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'type="hidden" name="questions-0-order"' in response.content


@pytest.mark.django_db
def test_reordered_formset_persists_new_order(client, owner):
    """Reordering on the client re-emits the order values; server saves them."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    q1 = Question.objects.create(
        survey=survey, text="First", type=Question.Type.OPEN_TEXT, order=1
    )
    q2 = Question.objects.create(
        survey=survey, text="Second", type=Question.Type.OPEN_TEXT, order=2
    )
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "X",
        "slug": "x",
        "status": "draft",
        **_management(prefix, total=2),
        f"{prefix}-INITIAL_FORMS": "2",
        f"{prefix}-0-id": str(q1.id),
        f"{prefix}-0-survey": str(survey.id),
        f"{prefix}-0-order": "2",
        f"{prefix}-0-text": "First",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
        f"{prefix}-0-required": "on",
        f"{prefix}-1-id": str(q2.id),
        f"{prefix}-1-survey": str(survey.id),
        f"{prefix}-1-order": "1",
        f"{prefix}-1-text": "Second",
        f"{prefix}-1-type": "open_text",
        f"{prefix}-1-config": "",
        f"{prefix}-1-required": "on",
    }
    response = client.post(
        reverse("surveys:edit", kwargs={"slug": survey.slug}), payload
    )
    assert response.status_code == 302
    q1.refresh_from_db()
    q2.refresh_from_db()
    assert q1.order == 2
    assert q2.order == 1


@pytest.mark.django_db
def test_question_required_defaults_to_true(owner):
    """Sanity: the column default is True so existing API callers don't break."""
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    q = Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, order=1
    )
    assert q.required is True


@pytest.mark.django_db
def test_builder_post_saves_required_when_checked(client, owner):
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "T",
        "slug": "t",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Q1",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
        f"{prefix}-0-required": "on",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    q = Survey.objects.get(slug="t").questions.first()
    assert q.required is True


@pytest.mark.django_db
def test_builder_post_saves_optional_when_unchecked(client, owner):
    """Browsers omit unchecked checkboxes from POST — Django reads as False."""
    client.force_login(owner)
    prefix = "questions"
    payload = {
        "title": "T",
        "slug": "t",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Q1",
        f"{prefix}-0-type": "open_text",
        f"{prefix}-0-config": "",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    q = Survey.objects.get(slug="t").questions.first()
    assert q.required is False


@pytest.mark.django_db
def test_builder_renders_required_checkbox(client, owner):
    survey = Survey.objects.create(owner=owner, title="X", slug="x")
    Question.objects.create(
        survey=survey, text="Q", type=Question.Type.OPEN_TEXT, order=1, required=True
    )
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": survey.slug}))
    assert response.status_code == 200
    assert b'name="questions-0-required"' in response.content


@pytest.mark.django_db
def test_config_dict_round_trip(client, owner):
    """Saving with a config object and reloading should keep it as a dict."""
    client.force_login(owner)
    prefix = "questions"
    config = {"choices": ["A", "B", "C"]}
    payload = {
        "title": "Pick",
        "slug": "pick",
        "status": "draft",
        **_management(prefix, total=1),
        f"{prefix}-0-order": "1",
        f"{prefix}-0-text": "Pick one",
        f"{prefix}-0-type": "multi_select",
        f"{prefix}-0-config": json.dumps(config),
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    survey = Survey.objects.get(slug="pick")
    q = survey.questions.first()
    assert q.config == config


def _question_payload(prefix, n):
    """Build a valid n-question payload for the builder formset."""
    out = {**_management(prefix, total=n)}
    for i in range(n):
        out[f"{prefix}-{i}-order"] = str(i + 1)
        out[f"{prefix}-{i}-text"] = f"Q{i + 1}"
        out[f"{prefix}-{i}-type"] = "open_text"
        out[f"{prefix}-{i}-config"] = ""
    return out


@pytest.mark.django_db
def test_builder_accepts_exactly_hard_limit_questions(client, owner):
    """Saving with exactly QUESTION_HARD_LIMIT questions succeeds."""
    client.force_login(owner)
    payload = {
        "title": "Max",
        "slug": "max",
        "status": "draft",
        **_question_payload("questions", QUESTION_HARD_LIMIT),
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    assert Survey.objects.get(slug="max").questions.count() == QUESTION_HARD_LIMIT


@pytest.mark.django_db
def test_builder_rejects_over_hard_limit_questions(client, owner):
    """Saving with HARD_LIMIT + 1 questions is rejected with a clear error."""
    client.force_login(owner)
    payload = {
        "title": "Too many",
        "slug": "too-many",
        "status": "draft",
        **_question_payload("questions", QUESTION_HARD_LIMIT + 1),
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 200
    assert Survey.objects.count() == 0
    assert b"at most" in response.content
    assert str(QUESTION_HARD_LIMIT).encode() in response.content


@pytest.mark.django_db
def test_builder_renders_question_count_banner(client, owner):
    """Banner element + thresholds must be rendered so the JS can drive it."""
    client.force_login(owner)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 200
    assert b'id="question-count-banner"' in response.content
    assert (
        f'data-warn-threshold="{QUESTION_WARN_THRESHOLD}"'.encode() in response.content
    )
    assert f'data-hard-limit="{QUESTION_HARD_LIMIT}"'.encode() in response.content


@pytest.mark.django_db
def test_builder_saves_description(client, owner):
    """Description posts through the survey form and persists on the model."""
    client.force_login(owner)
    payload = {
        "title": "With description",
        "slug": "with-description",
        "description": "Short paragraph **inviting** people in.",
        "status": "draft",
        **_management("questions", total=0),
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    survey = Survey.objects.get(slug="with-description")
    assert survey.description == "Short paragraph **inviting** people in."


@pytest.mark.django_db
def test_builder_renders_description_textarea(client, owner):
    """Builder shows a textarea for description — not just a text input."""
    client.force_login(owner)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 200
    assert b'name="description"' in response.content
    assert b"description-counter" in response.content


@pytest.mark.django_db
def test_builder_rejects_over_long_description(client, owner):
    """Description longer than DESCRIPTION_MAX_LENGTH is rejected."""
    from surveys.models import DESCRIPTION_MAX_LENGTH

    client.force_login(owner)
    payload = {
        "title": "Long",
        "slug": "long",
        "description": "x" * (DESCRIPTION_MAX_LENGTH + 1),
        "status": "draft",
        **_management("questions", total=0),
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 200
    assert Survey.objects.count() == 0
