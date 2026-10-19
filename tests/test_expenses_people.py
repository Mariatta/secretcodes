"""People page: adding someone by name, and inviting them later."""

import re
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from expenses.models import Event, ExpenseInvitation, Participant

User = get_user_model()


@pytest.fixture
def access_perm(db):
    return Permission.objects.get(
        codename="access_expenses", content_type__app_label="expenses"
    )


@pytest.fixture
def owner(client, access_perm):
    user = User.objects.create_user(
        username="owner", password="pw", email="owner@example.com"
    )
    user.user_permissions.add(access_perm)
    client.login(username="owner", password="pw")
    return user


@pytest.fixture
def event(owner):
    event = Event.objects.create(name="Trip", owner=owner, base_currency="USD")
    Participant.objects.create(event=event, user=owner, role=Participant.OWNER)
    return event


def _people_url(event):
    return reverse("expenses:invite_create", kwargs={"event_id": event.pk})


def _invite_url(event, participant):
    return reverse(
        "expenses:participant_invite",
        kwargs={"event_id": event.pk, "participant_id": participant.pk},
    )


def _grid(*rows):
    """POST data for the Add people grid; each row is (name, email, invite)."""
    data = {
        "people-TOTAL_FORMS": str(len(rows) + 1),
        "people-INITIAL_FORMS": "0",
    }
    for index, (name, email, invite) in enumerate(rows):
        data[f"people-{index}-display_name"] = name
        data[f"people-{index}-email"] = email
        if invite:
            data[f"people-{index}-invite"] = "on"
    return data


def test_add_several_people_inviting_only_ticked_rows_with_email(client, event):
    with patch("expenses.views.send_invitation_email") as mock_send:
        response = client.post(
            _people_url(event),
            _grid(
                ("Mom", "", True),
                ("Dad", "Dad@Example.com", False),
                ("Sis", "sis@example.com", True),
                ("", "bro@example.com", True),
            ),
        )
    assert response.status_code == 302
    assert response.url == _people_url(event)
    rows = {
        p.invited_email or p.display_name: p
        for p in event.participants.filter(user__isnull=True)
    }
    assert set(rows) == {"Mom", "dad@example.com", "sis@example.com", "bro@example.com"}
    assert rows["Mom"].role == Participant.MEMBER
    invited = set(ExpenseInvitation.objects.values_list("email", flat=True))
    assert invited == {"sis@example.com", "bro@example.com"}
    assert mock_send.call_count == 2
    assert ExpenseInvitation.objects.get(email="sis@example.com").display_name == "Sis"
    followed = client.get(response.url)
    assert "Added 4 people, sent 2 invitations." in followed.content.decode()


def test_add_one_person_without_invites_message(client, event):
    response = client.post(_people_url(event), _grid(("Mom", "", False)), follow=True)
    assert "Added 1 person." in response.content.decode()


def test_add_people_saves_nothing_when_a_row_is_invalid(client, event):
    response = client.post(
        _people_url(event),
        _grid(("Mom", "", False), ("Me again", "OWNER@example.com", True)),
    )
    assert response.status_code == 200
    assert event.participants.count() == 1
    row = response.context["people_formset"].forms[1]
    assert "already has this email" in row.errors["email"][0]
    assert "is-invalid" in str(row["email"])


def test_add_people_rejects_email_with_pending_invitation(client, event, owner):
    ExpenseInvitation.create(event=event, email="p@example.com", inviter=owner)
    response = client.post(_people_url(event), _grid(("P", "p@example.com", True)))
    assert response.status_code == 200
    assert (
        "pending invitation"
        in response.context["people_formset"].forms[0].errors["email"][0]
    )


def test_add_people_rejects_same_email_twice(client, event):
    response = client.post(
        _people_url(event),
        _grid(("A", "same@example.com", True), ("B", "Same@example.com", True)),
    )
    assert response.status_code == 200
    assert "only be used once" in str(
        response.context["people_formset"].non_form_errors()
    )


def test_add_people_needs_at_least_one_row(client, event):
    response = client.post(_people_url(event), _grid())
    assert response.status_code == 200
    assert "Fill in at least one person." in str(
        response.context["people_formset"].non_form_errors()
    )


def test_add_people_rejects_bad_email(client, event):
    response = client.post(_people_url(event), _grid(("A", "not-an-email", True)))
    assert response.status_code == 200
    assert response.context["people_formset"].forms[0].errors["email"]


def test_people_page_shows_status_and_invite_form(client, event, owner):
    Participant.objects.create(event=event, display_name="Mom")
    Participant.objects.create(
        event=event, display_name="Pending", invited_email="p@example.com"
    )
    ExpenseInvitation.create(event=event, email="p@example.com", inviter=owner)
    response = client.get(_people_url(event))
    statuses = {
        row["participant"].display_name or "owner": row["status"]
        for row in response.context["people"]
    }
    assert statuses["Mom"] == "not invited"
    assert statuses["Pending"] == "invited"
    assert "joined" in statuses.values()
    rows = {row["participant"].display_name: row for row in response.context["people"]}
    assert rows["Mom"]["invite_form"] is not None
    assert rows["Pending"]["invite_form"] is None


def test_invite_added_person_keeps_their_row(client, event):
    mom = Participant.objects.create(event=event, display_name="Mom")
    with patch("expenses.views.send_invitation_email") as mock_send:
        response = client.post(
            _invite_url(event, mom), {f"p{mom.pk}-email": "Mom@Example.com"}
        )
    assert response.status_code == 302
    mock_send.assert_called_once()
    mom.refresh_from_db()
    assert mom.invited_email == "mom@example.com"
    invitation = ExpenseInvitation.objects.get()
    assert invitation.display_name == "Mom"
    assert event.participants.count() == 2


def test_accepting_invite_links_the_added_person(client, event):
    mom = Participant.objects.create(event=event, display_name="Mom")
    with patch("expenses.views.send_invitation_email"):
        client.post(_invite_url(event, mom), {f"p{mom.pk}-email": "mom@example.com"})
    invitation = ExpenseInvitation.objects.get()
    mom_user = User.objects.create_user(
        username="mom", password="pw", email="mom@example.com"
    )
    client.logout()
    client.login(username="mom", password="pw")
    client.post(reverse("expenses:accept_invite", kwargs={"key": invitation.key}))
    mom.refresh_from_db()
    assert mom.user == mom_user
    assert event.participants.count() == 2


def test_invite_added_person_rejects_email_of_someone_else(client, event):
    mom = Participant.objects.create(event=event, display_name="Mom")
    response = client.post(
        _invite_url(event, mom), {f"p{mom.pk}-email": "owner@example.com"}
    )
    assert response.status_code == 200
    assert not ExpenseInvitation.objects.exists()
    rows = {row["participant"].pk: row for row in response.context["people"]}
    assert rows[mom.pk]["invite_form"].errors["email"]


def test_invite_added_person_404_for_linked_participant(client, event, owner):
    linked = event.participants.get(user=owner)
    response = client.post(
        _invite_url(event, linked), {f"p{linked.pk}-email": "x@example.com"}
    )
    assert response.status_code == 404


@pytest.mark.parametrize("view", ["add", "invite", "people"])
def test_people_actions_are_owner_only(client, event, access_perm, view):
    member = User.objects.create_user(username="member", password="pw")
    member.user_permissions.add(access_perm)
    Participant.objects.create(event=event, user=member, display_name="Member")
    mom = Participant.objects.create(event=event, display_name="Mom")
    client.logout()
    client.login(username="member", password="pw")
    if view == "add":
        response = client.post(_people_url(event), _grid(("X", "", False)))
    elif view == "invite":
        response = client.post(
            _invite_url(event, mom), {f"p{mom.pk}-email": "m@example.com"}
        )
    else:
        response = client.get(_people_url(event))
    assert response.status_code == 403
    assert not event.participants.filter(display_name="X").exists()


def test_invite_added_person_rejects_email_saved_on_another_added_person(client, event):
    Participant.objects.create(
        event=event, display_name="Dad", invited_email="dad@example.com"
    )
    mom = Participant.objects.create(event=event, display_name="Mom")
    response = client.post(
        _invite_url(event, mom), {f"p{mom.pk}-email": "dad@example.com"}
    )
    assert response.status_code == 200
    rows = {row["participant"].pk: row for row in response.context["people"]}
    assert "Someone else" in rows[mom.pk]["invite_form"].errors["email"][0]


def test_reinvite_with_pending_invitation_is_refused(client, event):
    mom = Participant.objects.create(event=event, display_name="Mom")
    with patch("expenses.views.send_invitation_email"):
        client.post(_invite_url(event, mom), {f"p{mom.pk}-email": "mom@example.com"})
        response = client.post(
            _invite_url(event, mom), {f"p{mom.pk}-email": "mom2@example.com"}
        )
    assert response.status_code == 302
    mom.refresh_from_db()
    assert mom.invited_email == "mom@example.com"
    assert ExpenseInvitation.objects.count() == 1


def test_people_page_ids_are_unique(client, event):
    Participant.objects.create(event=event, display_name="Mom")
    Participant.objects.create(event=event, display_name="Dad")
    body = client.get(_people_url(event)).content.decode()
    ids = re.findall(r'id="(id_[^"]+)"', body)
    assert len(ids) == len(set(ids))
