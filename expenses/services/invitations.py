"""Send the accept-invite email for an ExpenseInvitation.

Kept as a thin wrapper over `django.core.mail.send_mail` so tests can
patch this single function instead of mocking the SMTP layer.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone


def send_invitation_email(invitation, request) -> None:
    """Render the email body and dispatch it; mark `sent_at`."""
    accept_url = request.build_absolute_uri(
        reverse("expenses:accept_invite", kwargs={"key": invitation.key})
    )
    context = {
        "invitation": invitation,
        "accept_url": accept_url,
        "expiry_days": settings.EXPENSES_INVITATION_EXPIRY_DAYS,
    }
    subject = (
        f"{invitation.inviter.get_full_name() or invitation.inviter.get_username()} "
        f"invited you to {invitation.event.name}"
    )
    body = render_to_string("expenses/email/invite.txt", context)
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [invitation.email],
        fail_silently=False,
    )
    invitation.sent_at = timezone.now()
    invitation.save(update_fields=["sent_at", "modified_date"])
