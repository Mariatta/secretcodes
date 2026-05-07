"""Operations on Themes that span more than one row.

Single-row Theme edits go through the regular ModelForm; this module
holds the cross-row stuff (co-occurrence reads, merge writes).
"""

from collections import Counter

from django.db import transaction
from django.db.models import Count

from ..models import ResponseTheme, Theme


def co_occurring(theme: Theme) -> list[tuple[Theme, int]]:
    """Return other themes that share responses with this one, sorted desc.

    "Scheduling co-occurs with: venue (8), programming (5)" — the count is
    the number of *responses* tagged with both this theme and the other.
    """
    response_ids = list(theme.responses.values_list("id", flat=True))
    if not response_ids:
        return []
    rows = (
        ResponseTheme.objects.filter(response_id__in=response_ids)
        .exclude(theme=theme)
        .filter(theme__survey=theme.survey)
        .values_list("theme_id")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    counts = {theme_id: n for theme_id, n in rows}
    if not counts:
        return []
    others = Theme.objects.filter(id__in=counts.keys())
    by_id = {t.id: t for t in others}
    return [(by_id[tid], counts[tid]) for tid in counts if tid in by_id]


@transaction.atomic
def merge(source: Theme, target: Theme) -> None:
    """Move every Response from ``source`` into ``target`` and delete source.

    A Response already tagged on both is collapsed to a single ResponseTheme
    on target (the source row is dropped via cascade when source is deleted).
    Representative status from source is dropped — target keeps its own
    representative quote (if any), satisfying the one-per-theme constraint.
    """
    if source.pk == target.pk:
        return
    if source.survey_id != target.survey_id:
        raise ValueError("Themes must belong to the same survey to be merged.")
    target_response_ids = set(target.responses.values_list("id", flat=True))
    for rt in ResponseTheme.objects.filter(theme=source).select_related("response"):
        if rt.response_id in target_response_ids:
            continue
        rt.theme = target
        rt.is_representative = False
        rt.save()
    source.delete()
