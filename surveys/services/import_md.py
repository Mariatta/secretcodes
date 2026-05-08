"""Parse a markdown file describing a survey, then create the rows.

The markdown shape is intentionally simple — readable in any editor,
writeable by hand, no front-matter / no special parser dependencies::

    # Survey Title

    slug: post-event
    status: draft

    ## How would you rate the event?
    - type: rating
    - max: 5
    - labels: {"1": "Poor", "5": "Excellent"}

    ## Which sessions did you attend?
    - type: multi_select
    - choices: ["Talks", "Workshops", "Hallway"]
    - required: false

    ## Anything else?
    - type: open_text
    - required: false

Rules:

- Exactly one ``# H1`` heading at the top — the survey title.
- Survey-level metadata (slug, status) is ``key: value`` lines between
  the H1 and the first ``## H2``.
- Each ``## H2`` is a question; the heading text is the question wording.
- Question metadata is one ``- key: value`` line per property.
- ``type`` is required and must be one of ``rating``, ``multi_select``,
  ``nps``, ``open_text``, ``yes_no``.
- ``required`` defaults to ``true``; pass ``required: false`` to make
  a question optional.
- Any other key on a question becomes part of its ``config`` JSON.
  Values starting with ``[`` or ``{`` are parsed as JSON; ``true``/
  ``false`` become bool; bare integers become int; everything else
  stays a string.
"""

import json
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.text import slugify

from ..models import QUESTION_HARD_LIMIT, Question, Survey

VALID_TYPES = {"rating", "multi_select", "nps", "open_text", "yes_no"}
VALID_STATUSES = {"draft", "published", "closed"}

_KEY_VALUE_RE = re.compile(r"^-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$")


class MarkdownImportError(ValueError):
    """Raised on any parse / validation failure during import."""


@dataclass
class ParsedQuestion:
    text: str
    type: str
    config: dict = field(default_factory=dict)
    required: bool = True


@dataclass
class ParsedSurvey:
    title: str
    slug: str
    status: str
    questions: list[ParsedQuestion] = field(default_factory=list)


def _coerce(raw: str):
    """Best-effort value coercion for question metadata values."""
    raw = raw.strip()
    if raw.startswith(("[", "{")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MarkdownImportError(f"Invalid JSON value: {raw!r} ({exc})")
    lower = raw.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if raw.lstrip("-").isdigit():
        return int(raw)
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    return raw


def parse_markdown(text: str) -> ParsedSurvey:
    """Parse a markdown definition string into a ParsedSurvey.

    Raises ``MarkdownImportError`` on any structural problem.
    """
    lines = text.splitlines()
    i = 0
    n = len(lines)

    title = None
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            i += 1
            break
        i += 1
    if not title:
        raise MarkdownImportError(
            "Markdown must start with a single '# Title' heading for the survey title."
        )

    survey_meta: dict[str, str] = {}
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        if not stripped or stripped == "---":
            i += 1
            continue
        m = _KEY_VALUE_RE.match(stripped)
        if m:
            survey_meta[m.group(1).lower()] = m.group(2).strip()
        i += 1

    raw_slug = survey_meta.get("slug") or slugify(title)
    if not raw_slug:  # pragma: no cover
        raise MarkdownImportError(
            "Could not derive a slug from the title; add 'slug: my-survey' below the title."
        )
    status = survey_meta.get("status", "draft").lower()
    if status not in VALID_STATUSES:
        raise MarkdownImportError(
            f"status must be one of {sorted(VALID_STATUSES)} (got {status!r})."
        )

    questions: list[ParsedQuestion] = []
    while i < n:
        stripped = lines[i].strip()
        if not stripped.startswith("## "):
            i += 1
            continue
        q_text = stripped[3:].strip()
        if not q_text:  # pragma: no cover
            raise MarkdownImportError(
                f"Question heading on line {i + 1} has no text after '## '."
            )
        i += 1
        q_meta: dict[str, str] = {}
        while i < n:
            qline = lines[i].strip()
            if qline.startswith("## ") or qline.startswith("# "):
                break
            if not qline or qline == "---":
                i += 1
                continue
            m = _KEY_VALUE_RE.match(qline)
            if m:
                q_meta[m.group(1).lower()] = m.group(2).strip()
            i += 1

        q_type = q_meta.pop("type", "").lower()
        if not q_type:
            raise MarkdownImportError(f"Question {q_text!r} is missing a 'type:' line.")
        if q_type not in VALID_TYPES:
            raise MarkdownImportError(
                f"Question {q_text!r} has invalid type {q_type!r}. "
                f"Must be one of {sorted(VALID_TYPES)}."
            )
        required_raw = q_meta.pop("required", "true").lower()
        required = required_raw not in ("false", "no", "0", "")
        config = {key: _coerce(value) for key, value in q_meta.items()}
        questions.append(
            ParsedQuestion(text=q_text, type=q_type, config=config, required=required)
        )

    if not questions:
        raise MarkdownImportError(
            "Survey must include at least one '## Question' heading."
        )
    if len(questions) > QUESTION_HARD_LIMIT:
        raise MarkdownImportError(
            f"A survey can have at most {QUESTION_HARD_LIMIT} questions "
            f"(this file has {len(questions)})."
        )

    return ParsedSurvey(title=title, slug=raw_slug, status=status, questions=questions)


@transaction.atomic
def import_survey(parsed: ParsedSurvey, *, owner) -> Survey:
    """Persist a ParsedSurvey for ``owner``. Raises if the slug is taken."""
    if Survey.objects.filter(slug=parsed.slug).exists():
        raise MarkdownImportError(
            f"A survey with slug {parsed.slug!r} already exists. "
            "Edit the 'slug:' line in the markdown to a free name."
        )
    survey = Survey.objects.create(
        owner=owner,
        title=parsed.title,
        slug=parsed.slug,
        status=parsed.status,
    )
    for index, pq in enumerate(parsed.questions, start=1):
        Question.objects.create(
            survey=survey,
            text=pq.text,
            type=pq.type,
            config=pq.config,
            required=pq.required,
            order=index,
        )
    return survey
