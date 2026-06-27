"""Slug generation for Campaign and Post.

Slugs are regenerated from ``name`` / ``title`` on every save and track the
title (URLs are logged-in-only, never shared externally). Collisions are
resolved within the parent scope by appending ``-2``, ``-3``, etc. Slugs are
capped at the field's ``max_length`` and trimmed at the last word boundary
rather than mid-word.
"""

from django.utils.text import slugify

FALLBACK_SLUG = "item"


def _truncate_on_word_boundary(slug, max_length):
    """Trim ``slug`` to ``max_length``, cutting at the last ``-`` if possible."""
    if len(slug) <= max_length:
        return slug
    truncated = slug[:max_length]
    if "-" in truncated:
        truncated = truncated.rsplit("-", 1)[0]
    return truncated


def generate_unique_slug(*, value, max_length, queryset, reserved=frozenset()):
    """Slug for ``value`` unique across ``queryset`` (which must exclude self).

    ``queryset`` is the set of sibling rows to check against — for Campaign,
    other campaigns in the board; for Post, other posts in the campaign. A
    candidate that collides with ``reserved`` (e.g. board slugs that would clash
    with the URL structure) is also rejected and suffixed.
    """
    base = _truncate_on_word_boundary(slugify(value), max_length) or FALLBACK_SLUG
    candidate = base
    suffix_n = 2
    while candidate in reserved or queryset.filter(slug=candidate).exists():
        suffix = f"-{suffix_n}"
        candidate = _truncate_on_word_boundary(base, max_length - len(suffix)) + suffix
        suffix_n += 1
    return candidate
