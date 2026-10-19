"""Turning a ``Publication`` into a platform-agnostic ``PublishPayload``.

Kept apart from the connectors so that "what do we send" is one place, testable
without any platform, and identical to what preflight measured.
"""

import mimetypes

from django.conf import settings

from .connectors import AssetRef, PublishPayload

# The asset extensions the planner knows about, mapped for platforms that care.
EXTRA_MIME_TYPES = {
    ".avif": "image/avif",
    ".webp": "image/webp",
}


def mime_for(asset):
    """Best-effort MIME type from the asset's file or source URL."""
    extension = asset._media_extension
    if extension in EXTRA_MIME_TYPES:
        return EXTRA_MIME_TYPES[extension]
    return mimetypes.types_map.get(extension, "")


def absolute_url(url):
    """Connectors fetch assets over HTTP, so a MEDIA_URL path is not enough.

    Local storage yields "/media/…"; Spaces already yields an absolute URL.
    """
    if url.startswith("/"):
        return f"{settings.DOMAIN_NAME.rstrip('/')}{url}"
    return url


def asset_ref(asset):
    """The connector-facing view of one asset. ``caption`` is the alt text."""
    return AssetRef(
        url=absolute_url(asset.media_url),
        mime=mime_for(asset),
        alt=asset.caption,
        byte_size=asset.file.size if asset.file else 0,
    )


def render_text(post):
    """The text as it goes out: body plus hashtags, per the channel's rules."""
    return post.copy_text


def build_payload(publication):
    """Rendered text plus ordered assets for one publication."""
    return PublishPayload(
        text=render_text(publication.post),
        assets=[asset_ref(a) for a in publication.post.assets.all()],
        link=publication.post.published_url or None,
    )
