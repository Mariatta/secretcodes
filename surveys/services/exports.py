"""Export builders for survey data.

Two formats:

- ``build_csv(survey)`` — flat CSV: one row per submission, two metadata
  columns (``submission_uuid``, ``submitted_at``) followed by one column
  per question (header is the question text).
- ``build_action_items_markdown(survey)`` — markdown handoff doc: each
  theme with an action item, sorted by status / priority, with the
  starred representative quote.

Both functions return strings — the view layer wraps in ``HttpResponse``.
"""

import csv
import io

from django.db.models import Count

from ..models import Question, Response, Survey, Theme


_PRIORITY_RANK = {Theme.Priority.HIGH: 0, Theme.Priority.MEDIUM: 1, Theme.Priority.LOW: 2}
_STATUS_RANK = {
    Theme.Status.OPEN: 0,
    Theme.Status.IN_PROGRESS: 1,
    Theme.Status.RESOLVED: 2,
}


def _format_csv_cell(question: Question, value) -> str:
    """Render an answer for the CSV in a way that round-trips through Excel."""
    if value is None:
        return ""
    if question.type == Question.Type.MULTI_SELECT:
        if isinstance(value, list):
            return "; ".join(str(v) for v in value)
        return str(value)
    if question.type == Question.Type.YES_NO:
        if value is True:
            return "Yes"
        if value is False:
            return "No"
        return ""
    return str(value)


def build_csv(survey: Survey) -> str:
    """Return a CSV string of all submissions for the survey.

    Submissions are grouped by ``submission_uuid`` and ordered by their
    earliest ``submitted_at``. Missing answers render as empty cells.
    """
    questions = list(survey.questions.order_by("order"))
    rows = (
        Response.objects.filter(question__survey=survey)
        .select_related("question")
        .order_by("submitted_at")
    )

    grouped: dict[str, dict] = {}
    for r in rows:
        sid = str(r.submission_uuid)
        bucket = grouped.setdefault(
            sid, {"submitted_at": r.submitted_at, "answers": {}}
        )
        bucket["answers"][r.question_id] = r.value
        if r.submitted_at < bucket["submitted_at"]:
            bucket["submitted_at"] = r.submitted_at

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["submission_uuid", "submitted_at"]
    header.extend(q.text for q in questions)
    writer.writerow(header)

    sids_sorted = sorted(grouped.keys(), key=lambda s: grouped[s]["submitted_at"])
    for sid in sids_sorted:
        sub = grouped[sid]
        row = [sid, sub["submitted_at"].isoformat()]
        for q in questions:
            row.append(_format_csv_cell(q, sub["answers"].get(q.id)))
        writer.writerow(row)
    return buf.getvalue()


def build_action_items_markdown(survey: Survey) -> str:
    """Return a markdown handoff doc summarizing the survey's action items.

    Includes only themes with a non-empty ``action_item``. Sorted the
    same way the actions dashboard sorts: open before resolved, then by
    priority desc, then by name.
    """
    themes = list(
        survey.themes.annotate(
            mention_count=Count("responses", distinct=True)
        ).prefetch_related("responsetheme_set__response")
    )
    items = [t for t in themes if t.action_item.strip()]
    items.sort(
        key=lambda t: (
            _STATUS_RANK.get(t.status, 99),
            _PRIORITY_RANK.get(t.priority, 99),
            t.name.lower(),
        )
    )

    lines: list[str] = []
    lines.append(f"# {survey.title} — Action Items")
    lines.append("")
    if not items:
        lines.append("_No action items written yet._")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"_{len(items)} action {'item' if len(items) == 1 else 'items'}._")
    lines.append("")

    for theme in items:
        rep = next(
            (
                rt.response
                for rt in theme.responsetheme_set.all()
                if rt.is_representative
            ),
            None,
        )
        lines.append(f"## {theme.name}")
        meta_bits = []
        if theme.tag:
            meta_bits.append(f"`{theme.tag}`")
        meta_bits.append(f"**Priority:** {theme.get_priority_display()}")
        meta_bits.append(f"**Status:** {theme.get_status_display()}")
        meta_bits.append(
            f"**Mentions:** {theme.mention_count}"
        )
        lines.append(" · ".join(meta_bits))
        lines.append("")
        lines.append(theme.action_item.strip())
        if rep:
            quote = str(rep.value).strip()
            quoted = "\n".join("> " + line for line in quote.splitlines())
            lines.append("")
            lines.append(quoted)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
