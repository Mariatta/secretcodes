"""Format the list of people who will see a survey's responses.

Surfaced to respondents on the public survey page so they know who
their answers go to before submitting — the survey owner and every
accepted collaborator.
"""


def display_name(user):
    """Full name (``first_name last_name``) if set, else username.

    The default Django User has ``get_full_name()``, which returns the
    two name fields joined and stripped — empty string when neither is
    set. Falling back to ``username`` guarantees a non-empty label.
    """
    return user.get_full_name().strip() or user.username


def recipient_names(survey):
    """Display names of everyone with read access to ``survey``'s responses.

    Owner first, then collaborators in the order they joined. Returns a
    list of strings — joining/formatting is left to the caller.
    """
    names = [display_name(survey.owner)]
    for collab in survey.collaborators.select_related("user").order_by("joined_at"):
        names.append(display_name(collab.user))
    return names


def join_with_and(names):
    """English prose join with an Oxford comma.

    ``['A']``           → ``'A'``
    ``['A', 'B']``      → ``'A and B'``
    ``['A', 'B', 'C']`` → ``'A, B, and C'``
    """
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"
