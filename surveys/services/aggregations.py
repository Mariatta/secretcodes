"""Pure-function aggregations powering the results dashboard.

No HTTP, no template rendering, no I/O beyond the single ORM read.
Trivially unit-testable from a fixture survey.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..models import Question, Response, Survey

NPS_PROMOTER_MIN = 9
NPS_DETRACTOR_MAX = 6


@dataclass
class Bar:
    """One row of a horizontal-bar chart."""

    label: str
    count: int
    width_pct: int


@dataclass
class QuestionSummary:
    """Per-question aggregation. Shape varies by ``question.type``."""

    question: Question
    response_count: int = 0
    distribution: dict[Any, int] = field(default_factory=dict)
    bars: list[Bar] = field(default_factory=list)
    average: float | None = None
    nps_score: float | None = None
    open_text_count: int = 0
    max_value: int | None = None


def _bars_relative_to_max(distribution: dict[Any, int]) -> list[Bar]:
    """Bar widths normalized to the tallest bucket — for rating/NPS."""
    if not distribution:
        return []
    top = max(distribution.values()) or 1
    return [
        Bar(label=str(k), count=v, width_pct=round(v * 100 / top))
        for k, v in distribution.items()
    ]


def _bars_relative_to_total(distribution: dict[Any, int], total: int) -> list[Bar]:
    """Bar widths as % of total submissions — for multi_select/yes_no."""
    if not total:  # pragma: no cover
        return [
            Bar(label=str(k), count=v, width_pct=0) for k, v in distribution.items()
        ]
    return [
        Bar(label=str(k), count=v, width_pct=round(v * 100 / total))
        for k, v in distribution.items()
    ]


@dataclass
class SurveyAggregation:
    """Top-level aggregation for the results dashboard."""

    survey: Survey
    submission_count: int
    question_count: int
    completion_rate: float | None
    average_rating: float | None
    summaries: list[QuestionSummary]


def _summarize_rating(question: Question, values: list[int]) -> QuestionSummary:
    """Distribution + average. Always renders bars 1..max so empty buckets show."""
    max_value = int(question.config.get("max", 5))
    distribution = {i: 0 for i in range(1, max_value + 1)}
    for v in values:
        if v in distribution:
            distribution[v] += 1
    average = sum(values) / len(values) if values else None
    return QuestionSummary(
        question=question,
        response_count=len(values),
        distribution=distribution,
        bars=_bars_relative_to_max(distribution),
        average=average,
        max_value=max_value,
    )


def _summarize_nps(question: Question, values: list[int]) -> QuestionSummary:
    """Standard NPS: %(score 9-10) − %(score 0-6). Returns -100..100."""
    distribution = {i: 0 for i in range(11)}
    for v in values:
        if 0 <= v <= 10:
            distribution[v] += 1
    n = len(values)
    if n:
        promoters = sum(1 for v in values if v >= NPS_PROMOTER_MIN)
        detractors = sum(1 for v in values if v <= NPS_DETRACTOR_MAX)
        nps_score = (promoters - detractors) * 100 / n
        average = sum(values) / n
    else:
        nps_score = None
        average = None
    return QuestionSummary(
        question=question,
        response_count=n,
        distribution=distribution,
        bars=_bars_relative_to_max(distribution),
        average=average,
        nps_score=nps_score,
        max_value=10,
    )


def _summarize_multi_select(
    question: Question, values: list[list[str]]
) -> QuestionSummary:
    """Count occurrences of each choice across all submissions."""
    declared = question.config.get("choices", [])
    counter: Counter = Counter()
    for choices in values:
        for c in choices:
            counter[c] += 1
    distribution = {c: counter.get(c, 0) for c in declared}
    for c, n in counter.items():
        if c not in distribution:
            distribution[c] = n
    return QuestionSummary(
        question=question,
        response_count=len(values),
        distribution=distribution,
        bars=_bars_relative_to_total(distribution, len(values)),
    )


def _summarize_yes_no(question: Question, values: list[bool]) -> QuestionSummary:
    yes = sum(1 for v in values if v is True)
    no = sum(1 for v in values if v is False)
    distribution = {"Yes": yes, "No": no}
    return QuestionSummary(
        question=question,
        response_count=yes + no,
        distribution=distribution,
        bars=_bars_relative_to_total(distribution, yes + no),
    )


def _summarize_open_text(question: Question, values: list[str]) -> QuestionSummary:
    non_empty = sum(1 for v in values if v and v.strip())
    return QuestionSummary(
        question=question,
        response_count=non_empty,
        open_text_count=non_empty,
    )


_SUMMARIZERS = {
    Question.Type.RATING: _summarize_rating,
    Question.Type.NPS: _summarize_nps,
    Question.Type.MULTI_SELECT: _summarize_multi_select,
    Question.Type.YES_NO: _summarize_yes_no,
    Question.Type.OPEN_TEXT: _summarize_open_text,
}


def aggregate_survey(survey: Survey) -> SurveyAggregation:
    """Single ORM read; bucket responses per question; per-type summaries."""
    questions = list(survey.questions.all().order_by("order"))
    responses = list(
        Response.objects.filter(question__survey=survey).select_related("question")
    )
    grouped: dict[int, list] = {q.id: [] for q in questions}
    for r in responses:
        grouped.setdefault(r.question_id, []).append(r.value)

    summaries = []
    rating_values: list[int] = []
    for q in questions:
        values = grouped.get(q.id, [])
        summarizer = _SUMMARIZERS[q.type]
        summary = summarizer(q, values)
        summaries.append(summary)
        if q.type == Question.Type.RATING:
            rating_values.extend(v for v in values if isinstance(v, int))

    submission_count = len({r.submission_uuid for r in responses})
    question_count = len(questions)
    if submission_count and question_count:
        completion_rate = len(responses) / (submission_count * question_count)
    else:
        completion_rate = None
    average_rating = sum(rating_values) / len(rating_values) if rating_values else None

    return SurveyAggregation(
        survey=survey,
        submission_count=submission_count,
        question_count=question_count,
        completion_rate=completion_rate,
        average_rating=average_rating,
        summaries=summaries,
    )
