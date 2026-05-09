"""Template filters for surveys.

Currently exposes ``safe_markdown`` for rendering user-authored survey
descriptions: markdown → HTML, then bleach-cleaned to a small whitelist of
inline-formatting tags. Designed to be safe to render on the public
respondent page without trusting the survey owner's input.
"""

import bleach
import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ALLOWED_TAGS = frozenset({"p", "br", "strong", "em", "a", "code", "ul", "ol", "li"})
ALLOWED_ATTRIBUTES = {"a": ["href", "title"]}
ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})


@register.filter
def safe_markdown(text):
    """Render ``text`` as markdown and strip everything that isn't on the
    inline-formatting whitelist.

    Returns a marked-safe HTML string. Empty / None input yields ``""``.
    """
    if not text:
        return ""
    rendered = markdown.markdown(text, extensions=["nl2br"])
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return mark_safe(cleaned)
