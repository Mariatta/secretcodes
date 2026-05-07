import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from qrcode_manager.models import QRCode
from surveys.models import Survey
from surveys.services.publishing import ensure_short_url


@pytest.fixture
def owner(db, surveys_user_perm, surveys_create_perm):
    user = get_user_model().objects.create_user(username="owner", password="pw")
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


@pytest.mark.django_db
def test_published_survey_gets_short_url(owner):
    survey = Survey.objects.create(
        owner=owner,
        title="Post-event",
        slug="post-event",
        status=Survey.Status.PUBLISHED,
    )
    qr = ensure_short_url(survey)
    assert qr is not None
    survey.refresh_from_db()
    assert survey.short_url_id == qr.id
    assert qr.url.endswith("/surveys/post-event/")
    assert qr.slug  # non-empty
    assert qr.description == "Post-event"


@pytest.mark.django_db
def test_draft_survey_does_not_get_short_url(owner):
    survey = Survey.objects.create(
        owner=owner,
        title="Draft",
        slug="draft",
        status=Survey.Status.DRAFT,
    )
    qr = ensure_short_url(survey)
    assert qr is None
    survey.refresh_from_db()
    assert survey.short_url_id is None


@pytest.mark.django_db
def test_ensure_short_url_is_idempotent(owner):
    survey = Survey.objects.create(
        owner=owner,
        title="X",
        slug="x",
        status=Survey.Status.PUBLISHED,
    )
    first = ensure_short_url(survey)
    survey.refresh_from_db()
    second = ensure_short_url(survey)
    assert first.id == second.id
    assert QRCode.objects.count() == 1


@pytest.mark.django_db
def test_changing_survey_slug_resyncs_qr_destination(owner):
    """Editing survey.slug must reroute the short link to the new URL.

    The QR image encodes only the QR slug (which doesn't change), so
    the same printed/scanned QR keeps working after a slug rename.
    """
    survey = Survey.objects.create(
        owner=owner,
        title="X",
        slug="original",
        status=Survey.Status.PUBLISHED,
    )
    qr = ensure_short_url(survey)
    original_qr_slug = qr.slug
    assert qr.url.endswith("/surveys/original/")

    survey.slug = "renamed"
    survey.save()
    second = ensure_short_url(survey)
    assert second.id == qr.id
    assert second.slug == original_qr_slug  # short slug unchanged
    assert second.url.endswith("/surveys/renamed/")


@pytest.mark.django_db
def test_short_url_persists_after_status_change_to_closed(owner):
    """Closing a published survey must NOT remove the short URL."""
    survey = Survey.objects.create(
        owner=owner,
        title="X",
        slug="x",
        status=Survey.Status.PUBLISHED,
    )
    ensure_short_url(survey)
    survey.refresh_from_db()
    qr_id = survey.short_url_id

    survey.status = Survey.Status.CLOSED
    survey.save()
    ensure_short_url(survey)
    survey.refresh_from_db()
    assert survey.short_url_id == qr_id


@pytest.mark.django_db
def test_truncates_long_title_for_qr_description(owner):
    long_title = "A" * 80
    survey = Survey.objects.create(
        owner=owner,
        title=long_title,
        slug="long",
        status=Survey.Status.PUBLISHED,
    )
    qr = ensure_short_url(survey)
    assert len(qr.description) <= 30


@pytest.mark.django_db
def test_publishing_via_builder_creates_short_url(client, owner):
    """End-to-end: posting a published survey through the builder provisions a QR."""
    client.force_login(owner)
    payload = {
        "title": "T",
        "slug": "t",
        "status": "published",
        "questions-TOTAL_FORMS": "1",
        "questions-INITIAL_FORMS": "0",
        "questions-MIN_NUM_FORMS": "0",
        "questions-MAX_NUM_FORMS": "1000",
        "questions-0-order": "1",
        "questions-0-text": "Q",
        "questions-0-type": "open_text",
        "questions-0-config": "",
        "questions-0-required": "on",
    }
    response = client.post(reverse("surveys:new"), payload)
    assert response.status_code == 302
    survey = Survey.objects.get(slug="t")
    assert survey.short_url is not None
    assert survey.short_url.url.endswith("/surveys/t/")


@pytest.mark.django_db
def test_ensure_short_url_skips_when_s3_not_configured(owner, settings):
    """No USE_SPACES → ensure_short_url returns None instead of crashing.

    Reproduces the local-dev path where AWS settings aren't configured.
    Survey saves successfully, just with no QR provisioned.
    """
    del settings.AWS_S3_ENDPOINT_URL
    survey = Survey.objects.create(
        owner=owner,
        title="X",
        slug="x",
        status=Survey.Status.PUBLISHED,
    )
    qr = ensure_short_url(survey)
    assert qr is None
    survey.refresh_from_db()
    assert survey.short_url_id is None


@pytest.mark.django_db
def test_builder_renders_qr_preview_when_published(client, owner):
    survey = Survey.objects.create(
        owner=owner,
        title="X",
        slug="x",
        status=Survey.Status.PUBLISHED,
    )
    qr = ensure_short_url(survey)
    assert qr is not None, "ensure_short_url should provision for published surveys"
    client.force_login(owner)
    response = client.get(reverse("surveys:edit", kwargs={"slug": "x"}))
    assert response.status_code == 200
    assert b"short-url-card" in response.content
    assert b"http://mocked/qr.png" in response.content
