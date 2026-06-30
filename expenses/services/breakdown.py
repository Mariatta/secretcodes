"""Aggregate an event's expenses for the overview stats and dashboard charts.

All amounts are in the event's base currency. ``event_stats`` is the cheap,
no-JS summary shown on the overview; ``event_breakdown`` is the grouped chart
data for the dashboard page, returned as floats so it serializes cleanly into
the JSON the Chart.js front end reads.
"""

from django.db.models import Avg, Count, Max, Min, Sum

from ..models import ExpenseShare


def _f(value):
    """Decimal or None to a JSON-friendly float."""
    return float(value) if value is not None else 0.0


def event_stats(event):
    """At-a-glance numbers for the overview: totals, counts, date span."""
    expenses = event.expenses.all()
    agg = expenses.aggregate(
        total=Sum("base_amount"),
        count=Count("id"),
        average=Avg("base_amount"),
        largest=Max("base_amount"),
        first_date=Min("paid_at"),
        last_date=Max("paid_at"),
    )
    return {
        "total": _f(agg["total"]),
        "count": agg["count"] or 0,
        "average": _f(agg["average"]),
        "largest": _f(agg["largest"]),
        "first_date": agg["first_date"],
        "last_date": agg["last_date"],
        "categories": expenses.values("category").distinct().count(),
        "participants": event.participants.count(),
    }


def event_breakdown(event):
    """Grouped totals for the dashboard charts (by category, payer, share, time)."""
    expenses = event.expenses.all()

    by_category = [
        {"label": row["category__name"], "value": _f(row["total"])}
        for row in expenses.values("category__name")
        .annotate(total=Sum("base_amount"))
        .order_by("-total")
    ]

    by_payer = [
        {"label": row["payer__display_name"], "value": _f(row["total"])}
        for row in expenses.values("payer__display_name")
        .annotate(total=Sum("base_amount"))
        .order_by("-total")
    ]

    by_share = [
        {"label": row["participant__display_name"], "value": _f(row["total"])}
        for row in ExpenseShare.objects.filter(expense__event=event)
        .values("participant__display_name")
        .annotate(total=Sum("share_amount"))
        .order_by("-total")
    ]

    over_time = [
        {"label": row["paid_at"].strftime("%b %d"), "value": _f(row["total"])}
        for row in expenses.values("paid_at")
        .annotate(total=Sum("base_amount"))
        .order_by("paid_at")
    ]

    return {
        "currency": event.base_currency,
        "by_category": by_category,
        "by_payer": by_payer,
        "by_share": by_share,
        "over_time": over_time,
    }
