"""Send the accept-invite email for an ExpenseInvitation.

Email body lives as a single markdown template (`invite.md`). On send
we render Django template tags first, then dispatch the result two
ways: as the plain-text body (markdown is intentionally readable as
plain text), and as an `EmailMultiAlternatives` HTML alternative
produced by the `markdown` library. Email clients pick the best.
"""

import markdown
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

INVITE_TEMPLATE = "expenses/email/invite.md"
HTML_WRAPPER = (
    '<!doctype html><html><body style="font-family: -apple-system, '
    "BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
    'max-width: 600px; margin: 0 auto; padding: 1.5rem;">'
    "{body}"
    "</body></html>"
)


def _render_invite_bodies(invitation, request):
    """Render the markdown template once, return (text_body, html_body)."""
    context = {
        "invitation": invitation,
        "accept_url": request.build_absolute_uri(
            reverse("expenses:accept_invite", kwargs={"key": invitation.key})
        ),
        "privacy_url": request.build_absolute_uri(reverse("privacy")),
        "terms_url": request.build_absolute_uri(reverse("terms")),
        "expiry_days": settings.EXPENSES_INVITATION_EXPIRY_DAYS,
    }
    text_body = render_to_string(INVITE_TEMPLATE, context)
    html_body = HTML_WRAPPER.format(
        body=markdown.markdown(text_body, extensions=["extra"])
    )
    return text_body, html_body


def send_invitation_email(invitation, request) -> None:
    """Render the email body and dispatch it; mark `sent_at`."""
    text_body, html_body = _render_invite_bodies(invitation, request)
    subject = (
        f"{invitation.inviter.get_full_name() or invitation.inviter.get_username()} "
        f"invited you to {invitation.event.name}"
    )
    message = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [invitation.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    invitation.sent_at = timezone.now()
    invitation.save(update_fields=["sent_at", "modified_date"])
