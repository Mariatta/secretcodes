"""Send the accept-invite email for a SurveyInvitation.

Mirrors expenses.services.invitations: render the markdown body once,
use it as plain-text, then convert markdown → HTML and inject it into
the branded HTML wrapper for the ``EmailMultiAlternatives`` HTML
alternative.
"""

import markdown
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

INVITE_TEXT_TEMPLATE = "surveys/email/invite.md"
INVITE_HTML_TEMPLATE = "surveys/email/invite.html"


def _render_invite_bodies(invitation, request):
    """Render the markdown source then wrap into branded HTML."""
    context = {
        "invitation": invitation,
        "accept_url": request.build_absolute_uri(
            reverse("surveys:accept_invite", kwargs={"key": invitation.key})
        ),
        "privacy_url": request.build_absolute_uri(reverse("privacy")),
        "terms_url": request.build_absolute_uri(reverse("terms")),
        "expiry_days": settings.SURVEYS_INVITATION_EXPIRY_DAYS,
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
    """Render the email body and dispatch it; mark ``sent_at``."""
    text_body, html_body = _render_invite_bodies(invitation, request)
    inviter_name = (
        invitation.inviter.get_full_name() or invitation.inviter.get_username()
    )
    subject = (
        f"{inviter_name} invited you to collaborate on " f"{invitation.survey.title}"
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
