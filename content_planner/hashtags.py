"""Hashtag parsing and merging.

Hashtags are stored as free text (campaign-level defaults plus optional
per-post additions) and normalized to ``#tag`` form on the way out. They live
outside the post body so they stay reusable and channel-tunable; they're
appended to the copy text only for social channels.
"""

import re

_SEPARATORS = re.compile(r"[\s,]+")


def parse_hashtags(raw):
    """Split free text into normalized ``#tag`` tokens, de-duplicated.

    Accepts comma- or space-separated input, with or without leading ``#``.
    De-duplication is case-insensitive, keeping the first spelling.
    """
    tags = []
    seen = set()
    for token in _SEPARATORS.split(raw or ""):
        tag = token.lstrip("#").strip()
        if not tag:
            continue
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            tags.append("#" + tag)
    return tags


def merge_hashtags(*raws):
    """Merge several hashtag strings into one de-duplicated, ordered list."""
    tags = []
    seen = set()
    for raw in raws:
        for tag in parse_hashtags(raw):
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                tags.append(tag)
    return tags
