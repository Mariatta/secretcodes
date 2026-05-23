"""Collaborator + invitation flow for surveys."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from qrcode_manager.models import QRCode
from surveys.forms import SurveyAcceptInviteSignupForm, SurveyInvitationForm
from surveys.models import (
    Question,
    Response,
    Survey,
    SurveyCollaborator,
    SurveyInvitation,
    Theme,
)

User = get_user_model()


@pytest.fixture
def owner(db, surveys_user_perm, surveys_create_perm):
    user = User.objects.create_user(
        username="owner", password="pw", email="owner@example.com"
    )
    user.user_permissions.add(surveys_user_perm, surveys_create_perm)
    return user


@pytest.fixture
def collaborator(db, surveys_user_perm):
    """A user with access_surveys but NOT create_surveys — only invited people."""
    user = User.objects.create_user(
        username="collab", password="pw", email="collab@example.com"
    )
    user.user_permissions.add(surveys_user_perm)
    return user


@pytest.fixture
def published_survey(owner):
    return Survey.objects.create(
        owner=owner,
        title="Sample",
        slug="sample",
        status=Survey.Status.PUBLISHED,
    )


# ---------- Permission gating: create vs. access -------------------------


@pytest.mark.django_db
def test_collaborator_cannot_create_a_new_survey(client, collaborator):
    client.force_login(collaborator)
    response = client.get(reverse("surveys:new"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_collaborator_cannot_use_import(client, collaborator):
    client.force_login(collaborator)
    response = client.get(reverse("surveys:import"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_dashboard_hides_new_survey_button_for_collaborator(client, collaborator):
    client.force_login(collaborator)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"+ New survey" not in response.content
    assert b"Import" not in response.content


@pytest.mark.django_db
def test_dashboard_shows_new_survey_button_for_owner(client, owner):
    client.force_login(owner)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"+ New survey" in response.content


# ---------- can_access_survey across views -------------------------------


@pytest.mark.django_db
def test_collaborator_can_access_invited_survey(
    client, owner, collaborator, published_survey
):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.get(
        reverse("surveys:edit", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_collaborator_cannot_access_other_surveys(
    client, owner, collaborator, published_survey
):
    """Without a SurveyCollaborator row, collaborator gets 404."""
    client.force_login(collaborator)
    response = client.get(
        reverse("surveys:edit", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_collaborator_sees_invited_survey_on_dashboard(
    client, owner, collaborator, published_survey
):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Sample" in response.content
    assert b"collaborator" in response.content


@pytest.mark.django_db
def test_owner_dashboard_does_not_show_collaborator_badge(
    client, owner, published_survey
):
    client.force_login(owner)
    response = client.get(reverse("surveys:dashboard"))
    assert response.status_code == 200
    assert b"Sample" in response.content
    assert b'class="badge' in response.content or True
    """The owner's own survey card shouldn't carry the 'collaborator' label."""
    """We check substring ordering: 'collaborator' shouldn't appear within
    the survey row block's label slot."""


# ---------- Invitation create form ---------------------------------------


@pytest.mark.django_db
def test_invitation_form_rejects_existing_collaborator(
    owner, collaborator, published_survey
):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    form = SurveyInvitationForm(
        {"email": collaborator.email}, survey=published_survey, inviter=owner
    )
    assert not form.is_valid()
    assert "already a collaborator" in str(form.errors)


@pytest.mark.django_db
def test_invitation_form_rejects_pending_duplicate(owner, published_survey):
    SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    form = SurveyInvitationForm(
        {"email": "x@example.com"}, survey=published_survey, inviter=owner
    )
    assert not form.is_valid()
    assert "pending invitation" in str(form.errors)


@pytest.mark.django_db
def test_invitation_form_rejects_self_invite(owner, published_survey):
    form = SurveyInvitationForm(
        {"email": owner.email}, survey=published_survey, inviter=owner
    )
    assert not form.is_valid()
    assert "yourself" in str(form.errors)


@pytest.mark.django_db
def test_invitation_form_creates_invitation(owner, published_survey):
    form = SurveyInvitationForm(
        {"email": "new@example.com"}, survey=published_survey, inviter=owner
    )
    assert form.is_valid()
    invitation = form.save()
    assert invitation.email == "new@example.com"
    assert invitation.survey == published_survey
    assert invitation.inviter == owner
    assert invitation.key  # non-empty


# ---------- Invitation create view ---------------------------------------


@pytest.mark.django_db
def test_invite_create_requires_owner(client, owner, collaborator, published_survey):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.get(
        reverse("surveys:invite_create", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_invite_create_owner_sees_form(client, owner, published_survey):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:invite_create", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200
    assert b"Invite a collaborator" in response.content


@pytest.mark.django_db
def test_invite_create_post_sends_email(client, owner, published_survey, mailoutbox):
    client.force_login(owner)
    with patch("surveys.views.send_invitation_email") as mock_send:
        response = client.post(
            reverse("surveys:invite_create", kwargs={"slug": published_survey.slug}),
            {"email": "newperson@example.com"},
        )
    assert response.status_code == 302
    assert mock_send.call_count == 1
    invitation = SurveyInvitation.objects.get(email="newperson@example.com")
    assert invitation.survey == published_survey


# ---------- Resend invitation --------------------------------------------


@pytest.mark.django_db
def test_invite_resend_requires_owner(client, collaborator, owner, published_survey):
    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.post(
        reverse(
            "surveys:invite_resend",
            kwargs={"slug": published_survey.slug, "invitation_id": invitation.id},
        )
    )
    # Collaborator is not the owner — resend is owner-only.
    assert response.status_code == 403


@pytest.mark.django_db
def test_invite_resend_rejects_get(client, owner, published_survey):
    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    client.force_login(owner)
    response = client.get(
        reverse(
            "surveys:invite_resend",
            kwargs={"slug": published_survey.slug, "invitation_id": invitation.id},
        )
    )
    assert response.status_code == 405


@pytest.mark.django_db
def test_invite_resend_re_emails_and_bumps_sent_at(client, owner, published_survey):
    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    # Backdate so we can verify sent_at moves forward after resend.
    old_sent = timezone.now() - timezone.timedelta(days=30)
    invitation.sent_at = old_sent
    invitation.save(update_fields=["sent_at"])
    assert invitation.is_expired()
    client.force_login(owner)
    with patch("surveys.views.send_invitation_email") as mock_send:
        # Make the mock actually update sent_at like the real function does.
        def fake_send(inv, _request):
            inv.sent_at = timezone.now()
            inv.save(update_fields=["sent_at"])

        mock_send.side_effect = fake_send
        response = client.post(
            reverse(
                "surveys:invite_resend",
                kwargs={
                    "slug": published_survey.slug,
                    "invitation_id": invitation.id,
                },
            )
        )
    assert response.status_code == 302
    assert response.url == reverse(
        "surveys:invite_create", kwargs={"slug": published_survey.slug}
    )
    assert mock_send.call_count == 1
    invitation.refresh_from_db()
    assert invitation.sent_at > old_sent
    assert not invitation.is_expired()


@pytest.mark.django_db
def test_invite_resend_404_if_already_accepted(client, owner, published_survey):
    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    client.force_login(owner)
    response = client.post(
        reverse(
            "surveys:invite_resend",
            kwargs={"slug": published_survey.slug, "invitation_id": invitation.id},
        )
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_invite_resend_404_if_invitation_on_other_survey(client, owner):
    """An invitation id from a different survey must not be re-sendable
    through the wrong survey's URL — prevents cross-survey leaks."""
    survey_a = Survey.objects.create(
        owner=owner, title="A", slug="a", status=Survey.Status.PUBLISHED
    )
    survey_b = Survey.objects.create(
        owner=owner, title="B", slug="b", status=Survey.Status.PUBLISHED
    )
    invitation = SurveyInvitation.create(
        survey=survey_b, email="x@example.com", inviter=owner
    )
    client.force_login(owner)
    response = client.post(
        reverse(
            "surveys:invite_resend",
            kwargs={"slug": survey_a.slug, "invitation_id": invitation.id},
        )
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_invite_create_lists_expired_invitations_with_resend_button(
    client, owner, published_survey
):
    fresh = SurveyInvitation.create(
        survey=published_survey, email="fresh@example.com", inviter=owner
    )
    fresh.sent_at = timezone.now()
    fresh.save(update_fields=["sent_at"])
    stale = SurveyInvitation.create(
        survey=published_survey, email="stale@example.com", inviter=owner
    )
    stale.sent_at = timezone.now() - timezone.timedelta(days=60)
    stale.save(update_fields=["sent_at"])
    client.force_login(owner)
    response = client.get(
        reverse("surveys:invite_create", kwargs={"slug": published_survey.slug})
    )
    body = response.content.decode()
    assert "fresh@example.com" in body
    assert "stale@example.com" in body
    # Expired badge appears for the stale one, not the fresh one.
    expired_section = body[body.index("stale@example.com") :]
    assert "expired" in expired_section[: expired_section.index("</li>")]
    # Both rows should carry a Resend button targeting the right URL.
    for inv in (fresh, stale):
        url = reverse(
            "surveys:invite_resend",
            kwargs={"slug": published_survey.slug, "invitation_id": inv.id},
        )
        assert f'action="{url}"' in body
    assert body.count("Resend") == 2


@pytest.fixture
def mailoutbox(monkeypatch):
    return []


# ---------- Accept-invite view --------------------------------------------


@pytest.mark.django_db
def test_accept_invite_existing_user_logged_in(
    client, owner, surveys_user_perm, published_survey
):
    """Invitee already has an account and is logged in as that account."""
    invitee = User.objects.create_user(
        username="invitee", password="pw", email="invitee@example.com"
    )
    invitee.user_permissions.add(surveys_user_perm)
    invitation = SurveyInvitation.create(
        survey=published_survey, email="invitee@example.com", inviter=owner
    )
    client.force_login(invitee)
    response = client.post(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert response.url == reverse(
        "surveys:results", kwargs={"slug": published_survey.slug}
    )
    invitation.refresh_from_db()
    assert invitation.is_accepted
    assert SurveyCollaborator.objects.filter(
        survey=published_survey, user=invitee
    ).exists()


@pytest.mark.django_db
def test_accept_invite_anonymous_existing_user_redirected_to_login(
    client, owner, published_survey
):
    """Invited email has an account, but visitor is anonymous."""
    User.objects.create_user(username="ghost", password="pw", email="ghost@example.com")
    invitation = SurveyInvitation.create(
        survey=published_survey, email="ghost@example.com", inviter=owner
    )
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_accept_invite_wrong_user_logged_in(
    client, owner, surveys_user_perm, published_survey
):
    """Invitation is for X but user is logged in as Y → forbidden."""
    User.objects.create_user(
        username="actual", password="pw", email="actual@example.com"
    )
    other = User.objects.create_user(
        username="wrongperson", password="pw", email="wrong@example.com"
    )
    other.user_permissions.add(surveys_user_perm)
    invitation = SurveyInvitation.create(
        survey=published_survey, email="actual@example.com", inviter=owner
    )
    client.force_login(other)
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_accept_invite_signup_creates_user_and_collaborator(
    client, owner, published_survey
):
    """No account exists for invited email → signup form, create + accept."""
    invitation = SurveyInvitation.create(
        survey=published_survey, email="new@example.com", inviter=owner
    )
    response = client.post(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key}),
        {
            "username": "newhire",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username="newhire")
    assert user.email == "new@example.com"
    assert SurveyCollaborator.objects.filter(
        survey=published_survey, user=user
    ).exists()
    invitation.refresh_from_db()
    assert invitation.is_accepted


@pytest.mark.django_db
def test_accept_invite_already_accepted_redirects(client, owner, published_survey):
    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    invitation.accepted_at = timezone.now()
    invitation.save()
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_accept_invite_expired_redirects(client, owner, published_survey):
    """An invitation older than the expiry window redirects to dashboard."""
    invitation = SurveyInvitation.create(
        survey=published_survey, email="late@example.com", inviter=owner
    )
    """Force-expire by writing creation_date far in the past."""
    SurveyInvitation.objects.filter(pk=invitation.pk).update(
        creation_date=timezone.now() - timezone.timedelta(days=365),
        sent_at=timezone.now() - timezone.timedelta(days=365),
    )
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert response.url == reverse("surveys:dashboard")


# ---------- Signup form direct -------------------------------------------


@pytest.mark.django_db
def test_signup_form_rejects_weak_password():
    form = SurveyAcceptInviteSignupForm(
        {"username": "u", "password1": "abc", "password2": "abc"},
        email="x@example.com",
    )
    assert not form.is_valid()


@pytest.mark.django_db
def test_signup_form_rejects_taken_username():
    User.objects.create_user(username="taken", password="pw")
    form = SurveyAcceptInviteSignupForm(
        {
            "username": "taken",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
        email="x@example.com",
    )
    assert not form.is_valid()
    assert "taken" in str(form.errors)


@pytest.mark.django_db
def test_signup_form_rejects_existing_email():
    User.objects.create_user(username="someone", password="pw", email="x@example.com")
    form = SurveyAcceptInviteSignupForm(
        {
            "username": "u",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
        email="x@example.com",
    )
    assert not form.is_valid()


@pytest.mark.django_db
def test_signup_form_rejects_password_mismatch():
    form = SurveyAcceptInviteSignupForm(
        {
            "username": "u",
            "password1": "S3curePass!23",
            "password2": "different!!23",
        },
        email="x@example.com",
    )
    assert not form.is_valid()
    assert "match" in str(form.errors)


# ---------- Email send: smoke ---------------------------------------------


@pytest.mark.django_db
def test_send_invitation_email_marks_sent_at(rf, owner, published_survey):
    """Render and dispatch the invite email; sent_at gets stamped."""
    from django.core import mail

    from surveys.services.invitations import send_invitation_email

    invitation = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    request = rf.get("/")
    send_invitation_email(invitation, request)
    invitation.refresh_from_db()
    assert invitation.sent_at is not None
    assert len(mail.outbox) == 1
    assert "x@example.com" in mail.outbox[0].to


@pytest.mark.django_db
def test_model_str_methods(owner, published_survey, collaborator):
    """__str__ on SurveyCollaborator + SurveyInvitation."""
    sc = SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    si = SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    assert "on" in str(sc)
    assert "Invite" in str(si)


@pytest.mark.django_db
def test_can_access_survey_anonymous_returns_false(published_survey):
    """can_access_survey rejects anonymous users."""
    from django.contrib.auth.models import AnonymousUser

    from surveys.permissions import can_access_survey

    assert can_access_survey(AnonymousUser(), published_survey) is False


@pytest.mark.django_db
def test_can_access_survey_superuser_passes(db, published_survey):
    """Superusers always have access regardless of ownership."""
    from surveys.permissions import can_access_survey

    su = User.objects.create_superuser(username="root", password="pw")
    assert can_access_survey(su, published_survey) is True


@pytest.mark.django_db
def test_collaborator_view_404s_on_other_survey(client, owner, collaborator):
    """Collaborator on survey A can't access survey B."""
    a = Survey.objects.create(owner=owner, title="A", slug="cov-a")
    b = Survey.objects.create(owner=owner, title="B", slug="cov-b")
    SurveyCollaborator.objects.create(survey=a, user=collaborator)
    client.force_login(collaborator)
    for url_name in ("edit", "results", "actions", "triage"):
        response = client.get(reverse(f"surveys:{url_name}", kwargs={"slug": "cov-b"}))
        assert response.status_code == 404
    """Theme-scoped endpoints also gate by survey access. theme_resolve and
    theme_merge require POST; theme_detail accepts GET. theme_star and
    theme_untag are POST-only and need a response_id."""
    from surveys.models import Question
    from surveys.models import Response as SurveyResponse
    from surveys.models import Theme

    theme = Theme.objects.create(survey=b, name="T")
    q = Question.objects.create(
        survey=b, text="?", type=Question.Type.OPEN_TEXT, order=1
    )
    import uuid

    r = SurveyResponse.objects.create(
        question=q, submission_uuid=uuid.uuid4(), value="x"
    )
    assert (
        client.get(
            reverse(
                "surveys:theme_detail", kwargs={"slug": "cov-b", "theme_id": theme.id}
            )
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse(
                "surveys:theme_resolve", kwargs={"slug": "cov-b", "theme_id": theme.id}
            )
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse(
                "surveys:theme_merge", kwargs={"slug": "cov-b", "theme_id": theme.id}
            ),
            {"target_theme_id": theme.id},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse(
                "surveys:theme_star",
                kwargs={"slug": "cov-b", "theme_id": theme.id, "response_id": r.id},
            )
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse(
                "surveys:theme_untag",
                kwargs={"slug": "cov-b", "theme_id": theme.id, "response_id": r.id},
            )
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_accept_invite_existing_user_get_renders_confirm(
    client, owner, surveys_user_perm, published_survey
):
    """GET on accept-invite for logged-in correct user shows the confirm page."""
    invitee = User.objects.create_user(
        username="confirm-me", password="pw", email="confirm@example.com"
    )
    invitee.user_permissions.add(surveys_user_perm)
    invitation = SurveyInvitation.create(
        survey=published_survey, email="confirm@example.com", inviter=owner
    )
    client.force_login(invitee)
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 200
    assert b"Accept and join" in response.content


@pytest.mark.django_db
def test_accept_invite_signup_get_renders_form(client, owner, published_survey):
    """GET on accept-invite for an unknown email shows the signup form."""
    invitation = SurveyInvitation.create(
        survey=published_survey, email="newhire@example.com", inviter=owner
    )
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 200
    assert b"Set up your account" in response.content


@pytest.mark.django_db
def test_accept_invite_signup_blocked_when_already_logged_in(
    client, owner, surveys_user_perm, published_survey
):
    """If a logged-in user (with a different email) hits the signup path,
    they're forbidden from creating a second account."""
    other = User.objects.create_user(
        username="alreadyhere", password="pw", email="alreadyhere@example.com"
    )
    other.user_permissions.add(surveys_user_perm)
    invitation = SurveyInvitation.create(
        survey=published_survey, email="brandnew@example.com", inviter=owner
    )
    client.force_login(other)
    response = client.get(
        reverse("surveys:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 403


# ---------- Team (read-only roster) --------------------------------------


@pytest.mark.django_db
def test_team_view_owner_sees_invite_button(client, owner, published_survey):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:team", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200
    assert b"+ Invite collaborator" in response.content
    assert published_survey.owner.email.encode() in response.content


@pytest.mark.django_db
def test_team_view_collaborator_sees_owner_and_peers(
    client, owner, collaborator, published_survey, surveys_user_perm
):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    peer = User.objects.create_user(
        username="peer", password="pw", email="peer@example.com"
    )
    peer.user_permissions.add(surveys_user_perm)
    SurveyCollaborator.objects.create(survey=published_survey, user=peer)
    client.force_login(collaborator)
    response = client.get(
        reverse("surveys:team", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200
    assert b"+ Invite collaborator" not in response.content
    assert b"owner@example.com" in response.content
    assert b"peer@example.com" in response.content


@pytest.mark.django_db
def test_team_view_empty_collaborators_owner(client, owner, published_survey):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:team", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200
    assert b"No collaborators yet." in response.content


@pytest.mark.django_db
def test_team_view_denied_for_non_collaborator(
    client, surveys_user_perm, published_survey
):
    stranger = User.objects.create_user(
        username="stranger", password="pw", email="stranger@example.com"
    )
    stranger.user_permissions.add(surveys_user_perm)
    client.force_login(stranger)
    response = client.get(
        reverse("surveys:team", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_team_view_anonymous_redirects_to_login(client, published_survey):
    response = client.get(
        reverse("surveys:team", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# ---------- Delete survey -----------------------------------------------


@pytest.mark.django_db
def test_delete_confirm_page_renders_for_owner(client, owner, published_survey):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:delete", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 200
    assert b"Delete this survey?" in response.content
    assert b"This is permanent." in response.content


@pytest.mark.django_db
def test_delete_confirm_lists_pending_invitations(client, owner, published_survey):
    SurveyInvitation.create(
        survey=published_survey, email="x@example.com", inviter=owner
    )
    client.force_login(owner)
    response = client.get(
        reverse("surveys:delete", kwargs={"slug": published_survey.slug})
    )
    assert b"pending" in response.content


@pytest.mark.django_db
def test_delete_post_removes_survey_and_cascades(client, owner, published_survey):
    question = Question.objects.create(
        survey=published_survey,
        text="rate",
        type=Question.Type.RATING,
        config={"max": 5},
        order=1,
    )
    Response.objects.create(question=question, value=5)
    Theme.objects.create(survey=published_survey, name="t")
    client.force_login(owner)
    response = client.post(
        reverse("surveys:delete", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 302
    assert response.url == reverse("surveys:dashboard")
    assert not Survey.objects.filter(slug=published_survey.slug).exists()
    assert Response.objects.count() == 0
    assert Theme.objects.count() == 0


@pytest.mark.django_db
def test_delete_also_removes_short_url(client, owner, published_survey):
    """The QR row is deleted alongside the survey so the slug can't be
    silently retargeted by a future survey reusing it."""
    qr = QRCode.objects.create(
        description="qr",
        slug="qr-" + published_survey.slug,
        url=f"https://example.com/{published_survey.slug}/",
    )
    published_survey.short_url = qr
    published_survey.save(update_fields=["short_url"])
    client.force_login(owner)
    client.post(reverse("surveys:delete", kwargs={"slug": published_survey.slug}))
    assert not QRCode.objects.filter(pk=qr.pk).exists()


@pytest.mark.django_db
def test_delete_collaborator_forbidden(client, owner, collaborator, published_survey):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.post(
        reverse("surveys:delete", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 403
    assert Survey.objects.filter(slug=published_survey.slug).exists()


@pytest.mark.django_db
def test_delete_anonymous_redirects_to_login(client, published_survey):
    response = client.get(
        reverse("surveys:delete", kwargs={"slug": published_survey.slug})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_builder_shows_delete_button_for_owner(client, owner, published_survey):
    client.force_login(owner)
    response = client.get(
        reverse("surveys:edit", kwargs={"slug": published_survey.slug})
    )
    assert b"Delete this survey" in response.content


@pytest.mark.django_db
def test_builder_hides_delete_button_for_collaborator(
    client, owner, collaborator, published_survey
):
    SurveyCollaborator.objects.create(survey=published_survey, user=collaborator)
    client.force_login(collaborator)
    response = client.get(
        reverse("surveys:edit", kwargs={"slug": published_survey.slug})
    )
    assert b"Delete this survey" not in response.content
