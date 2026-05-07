"""Helpers for the manual-tagging triage flow.

Triage operates on **open-text** responses only — other types are
analyzed in the results dashboard. A response is "triaged" once it
carries at least one ResponseTheme row, has been auto-marked as not
actionable (whitespace), or has been explicitly flagged.
"""

from django.db import transaction

from ..models import Question, Response, ResponseTheme, Survey, Theme

"""Quick-action keys that map to (case-insensitive) theme names.

These are mutually exclusive with regular themes: applying one clears any
other ResponseTheme rows on the same response, and applying a regular
theme on a response already tagged with one of these clears them.

``flag`` is intentionally NOT here — flag is a status on Response
(``is_flagged``), not a theme.
"""
QUICK_ACTION_THEME_NAMES = {
    "appreciation": "Appreciation",
    "not_actionable": "Not actionable",
}


def open_text_queue(survey: Survey):
    """All open-text responses for this survey, oldest first."""
    return (
        Response.objects.filter(
            question__survey=survey,
            question__type=Question.Type.OPEN_TEXT,
        )
        .select_related("question")
        .order_by("submitted_at", "id")
    )


def untriaged_queue(survey: Survey):
    """Open-text responses with no theme tags yet, oldest first."""
    return open_text_queue(survey).filter(themes__isnull=True).distinct()


def next_to_review(survey: Survey, after_id: int | None = None) -> Response | None:
    """Return the next response to triage.

    If ``after_id`` is given, skip responses up to and including it —
    used by the Skip action so the same row doesn't reappear immediately.
    """
    queue = untriaged_queue(survey)
    if after_id is not None:
        queue = queue.filter(id__gt=after_id)
    return queue.first()


def progress(survey: Survey) -> tuple[int, int]:
    """Return (reviewed, total) for the open-text queue."""
    total = open_text_queue(survey).count()
    untriaged = untriaged_queue(survey).count()
    return total - untriaged, total


def queue_neighbors(survey: Survey, response_id: int) -> tuple[int | None, int | None]:
    """Return ``(prev_id, next_id)`` in the full open-text queue.

    Used by triage prev/next nav. Walks the entire ordered queue regardless
    of triage state, so the organizer can revisit and edit prior tags.
    """
    ids = list(open_text_queue(survey).values_list("id", flat=True))
    try:
        idx = ids.index(response_id)
    except ValueError:
        return None, None
    prev_id = ids[idx - 1] if idx > 0 else None
    next_id = ids[idx + 1] if idx < len(ids) - 1 else None
    return prev_id, next_id


def _find_theme_case_insensitive(survey: Survey, name: str) -> Theme | None:
    """Return a theme on this survey matching ``name`` ignoring case."""
    return Theme.objects.filter(survey=survey, name__iexact=name).first()


def _get_or_create_theme(survey: Survey, name: str) -> Theme:
    """Case-insensitive get-or-create. Avoids creating "scheduling" alongside
    "Scheduling" — the spec calls out this as a footgun otherwise."""
    existing = _find_theme_case_insensitive(survey, name)
    if existing:
        return existing
    return Theme.objects.create(survey=survey, name=name)


@transaction.atomic
def apply_triage(
    *,
    response: Response,
    theme_ids: list[int],
    new_theme_name: str | None,
    quick_action: str | None,
    user,
) -> list[Theme]:
    """Apply tag changes to a response.

    - ``theme_ids`` — existing Theme rows on this survey to attach.
    - ``new_theme_name`` — optional fresh theme to create + attach
      (case-insensitive lookup; reuses existing theme on match).
    - ``quick_action`` — ``"appreciation"`` or ``"not_actionable"``;
      mutually exclusive with regular themes (clears all other tags
      on the response and replaces with just the quick-action theme).

    When regular themes are applied (``theme_ids`` or ``new_theme_name``)
    on a response already tagged with appreciation/not-actionable, the
    quick-action tags are removed first.
    """
    survey = response.question.survey

    if quick_action in QUICK_ACTION_THEME_NAMES:
        """Quick action mode: clear everything else, attach only this theme."""
        ResponseTheme.objects.filter(response=response).delete()
        theme = _get_or_create_theme(survey, QUICK_ACTION_THEME_NAMES[quick_action])
        ResponseTheme.objects.create(
            response=response,
            theme=theme,
            tagged_by=user if user.is_authenticated else None,
        )
        return [theme]

    themes_to_attach: list[Theme] = []
    if theme_ids:
        themes_to_attach.extend(Theme.objects.filter(survey=survey, id__in=theme_ids))
    if new_theme_name and new_theme_name.strip():
        themes_to_attach.append(_get_or_create_theme(survey, new_theme_name.strip()))

    if themes_to_attach:
        """Regular themes are mutually exclusive with quick-action sentinels —
        if the user added a real theme to a previously appreciated/not-actionable
        response, drop the sentinel."""
        sentinel_names = list(QUICK_ACTION_THEME_NAMES.values())
        ResponseTheme.objects.filter(
            response=response,
            theme__name__in=sentinel_names,
        ).delete()

    seen = set()
    for theme in themes_to_attach:
        if theme.id in seen:  # pragma: no cover
            continue
        seen.add(theme.id)
        ResponseTheme.objects.get_or_create(
            response=response,
            theme=theme,
            defaults={"tagged_by": user if user.is_authenticated else None},
        )

    return list({t.id: t for t in themes_to_attach}.values())


def toggle_flag(response: Response) -> bool:
    """Flip ``is_flagged`` on a response. Returns the new state."""
    response.is_flagged = not response.is_flagged
    response.save(update_fields=["is_flagged"])
    return response.is_flagged


def auto_mark_whitespace_not_actionable(response: Response, user) -> bool:
    """Auto-tag whitespace-only responses as Not actionable on first view.

    Idempotent — only fires when the response has no existing theme tags.
    Returns True if anything was applied.
    """
    raw = response.value
    text = raw if isinstance(raw, str) else ""
    if text.strip():
        return False
    if response.themes.exists():
        return False
    apply_triage(
        response=response,
        theme_ids=[],
        new_theme_name=None,
        quick_action="not_actionable",
        user=user,
    )
    return True
