"""Send the accept-invite email for an ExpenseInvitation.

Email body lives as a single markdown template (`invite.md`). The HTML
wrapper lives as a separate template (`invite.html`). On send we render
the markdown once, use it as the plain-text body, then convert markdown
→ HTML and inject it into the branded wrapper for the
`EmailMultiAlternatives` HTML alternative. Both templates render via
`django.template.loader.render_to_string`.
"""

import markdown
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

INVITE_TEXT_TEMPLATE = "expenses/email/invite.md"
INVITE_HTML_TEMPLATE = "expenses/email/invite.html"


def _render_invite_bodies(invitation, request):
    """Render the markdown source then wrap into branded HTML."""
    context = {
        "invitation": invitation,
        "accept_url": request.build_absolute_uri(
            reverse("expenses:accept_invite", kwargs={"key": invitation.key})
        ),
        "privacy_url": request.build_absolute_uri(reverse("privacy")),
        "terms_url": request.build_absolute_uri(reverse("terms")),
        "expiry_days": settings.EXPENSES_INVITATION_EXPIRY_DAYS,
    }
    text_body = render_to_string(INVITE_TEXT_TEMPLATE, context)
    rendered_html = markdown.markdown(text_body, extensions=["extra"])
    html_body = render_to_string(
        INVITE_HTML_TEMPLATE,
        {
            "body": rendered_html,
            "favicon_url": request.build_absolute_uri(static("brand/favicon.png")),
        },
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
