"""Invitation create + accept flow."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from expenses.forms import InvitationForm
from expenses.models import Event, ExpenseInvitation, Participant
from expenses.permissions import EXPENSES_GROUP

User = get_user_model()


@pytest.fixture
def expenses_group(db):
    group, _ = Group.objects.get_or_create(name=EXPENSES_GROUP)
    return group


@pytest.fixture
def owner(db, expenses_group):
    user = User.objects.create_user(username="owner", password="pw", email="o@x")
    user.groups.add(expenses_group)
    return user


@pytest.fixture
def event(db, owner):
    event = Event.objects.create(name="Trip", owner=owner, base_currency="USD")
    Participant.objects.create(event=event, user=owner, display_name="Owner")
    return event


def test_invitation_form_creates_placeholder_participant(event, owner):
    form = InvitationForm(
        {"email": "guest@example.com", "display_name": "Guest"},
        event=event,
        inviter=owner,
    )
    assert form.is_valid(), form.errors
    invitation = form.save()
    assert invitation.email == "guest@example.com"
    assert invitation.key
    assert event.participants.filter(invited_email="guest@example.com").exists()


def test_invitation_form_rejects_duplicate_pending(event, owner):
    first = InvitationForm(
        {"email": "dupe@example.com", "display_name": ""},
        event=event,
        inviter=owner,
    )
    assert first.is_valid()
    first.save()
    form = InvitationForm(
        {"email": "dupe@example.com", "display_name": ""},
        event=event,
        inviter=owner,
    )
    assert not form.is_valid()
    assert "email" in form.errors


def test_invite_create_view_owner_only(client, event, owner):
    other = User.objects.create_user(username="rando", password="pw")
    Participant.objects.create(event=event, user=other, display_name="Rando")
    other.groups.add(Group.objects.get(name=EXPENSES_GROUP))
    client.login(username="rando", password="pw")
    response = client.get(
        reverse("expenses:invite_create", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 403


def test_invite_create_view_owner_can_invite(client, event, owner):
    client.login(username="owner", password="pw")
    with patch("expenses.views.send_invitation_email") as mock_send:
        response = client.post(
            reverse("expenses:invite_create", kwargs={"event_id": event.pk}),
            {"email": "guest@example.com", "display_name": "Guest"},
        )
    assert response.status_code == 302
    assert ExpenseInvitation.objects.filter(email="guest@example.com").exists()
    mock_send.assert_called_once()


def test_accept_invite_links_user_and_grants_group(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="g@x", inviter=owner, display_name="G"
    )
    Participant.objects.create(event=event, invited_email="g@x", display_name="G")
    guest = User.objects.create_user(username="guest", password="pw", email="g@x")
    client.login(username="guest", password="pw")

    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    invitation.refresh_from_db()
    assert invitation.is_accepted
    assert guest.groups.filter(name=EXPENSES_GROUP).exists()
    participant = event.participants.get(invited_email="g@x")
    assert participant.user == guest
    assert participant.joined_at is not None


def test_accept_invite_rejects_email_mismatch(client, event, owner):
    """Wrong-email path when an account for the invited email also exists."""
    invitation = ExpenseInvitation.create(
        event=event, email="invited@x", inviter=owner, display_name="Invited"
    )
    User.objects.create_user(username="invited_user", password="pw", email="invited@x")
    other = User.objects.create_user(username="other", password="pw", email="other@x")
    client.login(username="other", password="pw")
    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 403
    invitation.refresh_from_db()
    assert not invitation.is_accepted


def test_accept_invite_requires_login_when_user_exists(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="g@x", inviter=owner, display_name="G"
    )
    User.objects.create_user(username="g", password="pw", email="g@x")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_accept_invite_shows_signup_form_for_unknown_email(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="newbie@x", inviter=owner, display_name="Newbie"
    )
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "newbie@x" in content
    assert "Username" in content


def test_accept_invite_signup_creates_user_and_links(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="newbie@x", inviter=owner, display_name="Newbie"
    )
    Participant.objects.create(
        event=event, invited_email="newbie@x", display_name="Newbie"
    )
    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key}),
        {
            "username": "newbie",
            "first_name": "New",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username="newbie")
    assert user.email == "newbie@x"
    assert user.check_password("S3curePass!23")
    assert user.groups.filter(name=EXPENSES_GROUP).exists()
    invitation.refresh_from_db()
    assert invitation.is_accepted
    assert event.participants.get(invited_email="newbie@x").user == user


def test_accept_invite_signup_rejects_password_mismatch(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="newbie@x", inviter=owner, display_name="Newbie"
    )
    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key}),
        {
            "username": "newbie",
            "password1": "S3curePass!23",
            "password2": "different!23",
        },
    )
    assert response.status_code == 200
    assert not User.objects.filter(username="newbie").exists()


def test_accept_invite_redirects_existing_email_to_login_with_message(
    client, event, owner
):
    """If an account already exists for the invited email, redirect to
    login with a flash message rather than allowing duplicate signup."""
    invitation = ExpenseInvitation.create(
        event=event, email="newbie@x", inviter=owner, display_name="Newbie"
    )
    User.objects.create_user(username="preexisting", password="pw", email="newbie@x")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key}),
        follow=True,
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "already exists" in body
    assert "log in" in body.lower()


def test_send_invitation_email_dispatches_and_marks_sent(
    client, event, owner, mailoutbox
):
    """End-to-end: invite_create POST renders the email + sets sent_at."""
    client.login(username="owner", password="pw")
    response = client.post(
        reverse("expenses:invite_create", kwargs={"event_id": event.pk}),
        {"email": "send_test@example.com", "display_name": "Send Test"},
    )
    assert response.status_code == 302
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert "send_test@example.com" in message.to
    assert event.name in message.subject
    assert "/expenses/accept/" in message.body
    invite = ExpenseInvitation.objects.get(email="send_test@example.com")
    assert invite.sent_at is not None


def test_accept_invite_already_accepted_redirects(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="alreadyaccepted@x", inviter=owner, display_name="A"
    )
    invitation.accepted_at = timezone_now()
    invitation.save()
    user = User.objects.create_user(
        username="aa", password="pw", email="alreadyaccepted@x"
    )
    user.groups.add(Group.objects.get(name=EXPENSES_GROUP))
    client.login(username="aa", password="pw")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert f"/expenses/events/{event.pk}/" in response.url


def test_accept_invite_expired_redirects_to_event_list(client, event, owner):
    """An expired invitation redirects with an error flash, not a 404."""
    invitation = ExpenseInvitation.create(
        event=event, email="expired@x", inviter=owner, display_name="E"
    )
    invitation.creation_date = _ages_ago()
    invitation.save()
    user = User.objects.create_user(username="ex", password="pw", email="expired@x")
    user.groups.add(Group.objects.get(name=EXPENSES_GROUP))
    client.login(username="ex", password="pw")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 302
    assert "/expenses/" in response.url


def test_accept_invite_signup_blocks_authenticated_user(client, event, owner):
    """A logged-in user who hits a no-account-yet invite gets a 403."""
    invitation = ExpenseInvitation.create(
        event=event, email="brand_new@x", inviter=owner, display_name="N"
    )
    other = User.objects.create_user(
        username="someoneelse", password="pw", email="other@x"
    )
    client.login(username="someoneelse", password="pw")
    response = client.get(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    assert response.status_code == 403


def test_invite_create_get_renders_pending_list(client, event, owner):
    """GET on the invite page shows pending invitations for the event."""
    ExpenseInvitation.create(
        event=event, email="pending@x", inviter=owner, display_name="Pending"
    )
    client.login(username="owner", password="pw")
    response = client.get(
        reverse("expenses:invite_create", kwargs={"event_id": event.pk})
    )
    assert response.status_code == 200
    assert b"pending@x" in response.content


def test_accept_invite_signup_uses_first_name_for_display_name(client, event, owner):
    """When invitation has no display_name, signup falls back to first_name."""
    invitation = ExpenseInvitation.create(
        event=event,
        email="nodisplay@x",
        inviter=owner,
        display_name="",
    )
    Participant.objects.create(
        event=event, invited_email="nodisplay@x", display_name=""
    )
    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key}),
        {
            "username": "nodisplay",
            "first_name": "Nick",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
    )
    assert response.status_code == 302
    participant = event.participants.get(invited_email="nodisplay@x")
    assert participant.display_name == "Nick"


def timezone_now():
    from django.utils import timezone

    return timezone.now()


def _ages_ago():
    """A datetime far enough in the past that any invite is expired."""
    import datetime

    from django.utils import timezone

    return timezone.now() - datetime.timedelta(days=365)


def test_accept_invite_signup_form_rejects_race_condition(event, owner):
    """Form-level defense: if a user with the email is created between
    view-check and form-submit, the form refuses on clean()."""
    from expenses.forms import AcceptInviteSignupForm

    User.objects.create_user(username="racewinner", password="pw", email="r@x")
    form = AcceptInviteSignupForm(
        {
            "username": "newbie",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
        email="r@x",
    )
    assert not form.is_valid()
    assert any("already has an account" in str(err) for err in form.non_field_errors())


def test_accept_invite_signup_rejects_existing_username(client, event, owner):
    invitation = ExpenseInvitation.create(
        event=event, email="newbie@x", inviter=owner, display_name="Newbie"
    )
    User.objects.create_user(username="taken", password="pw", email="other@x")
    response = client.post(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key}),
        {
            "username": "taken",
            "password1": "S3curePass!23",
            "password2": "S3curePass!23",
        },
    )
    assert response.status_code == 200
    assert User.objects.filter(username="taken").count() == 1
