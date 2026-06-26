"""Tag resolution for campaign forms and (later) chat import.

Tags are per-board with case-insensitive names. Typed names are matched against
the board's existing tags case-insensitively; unknown names create new rows.
"""

from .models import Tag


def parse_tag_names(raw):
    """Split a comma-separated tag string into cleaned, de-duplicated names.

    De-duplication is case-insensitive so "PyCon, pycon" yields one name,
    preserving the first spelling the user typed.
    """
    names = []
    seen = set()
    for chunk in raw.split(","):
        name = chunk.strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def resolve_tags(board, names):
    """Return Tag rows for ``names`` in ``board``, creating any that are new."""
    tags = []
    for name in names:
        tag = board.tags.filter(name__iexact=name).first()
        if tag is None:
            tag = Tag.objects.create(board=board, name=name)
        tags.append(tag)
    return tags
